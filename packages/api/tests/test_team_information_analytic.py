"""Team information analytic: nearest-planet territory geometry."""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.analytics import team_territory
from api.analytics.catalog import catalog_entry
from api.analytics.team_information import ANALYTIC_ID, REGISTRATION, get_team_information
from api.analytics.team_territory import TerritoryRingError, TerritorySite, territory_components
from api.models.player import Player

from tests.homeworld_locator_test_helpers import _planet, load_sample_turn

KIND_ALL = "team-territory"
KIND_OWNED = "team-territory-owned-only"


def _roster_player(template: Player, *, player_id: int, league_team_id: int) -> Player:
    return replace(
        template,
        id=player_id,
        username=f"player-{player_id}",
        leagueteamid=league_team_id,
    )


def _territory_turn(
    sites: list[tuple[int, int, int, int, int]],
    *,
    sphere: bool,
    width: int,
    height: int,
    mapshape: int = 4,
    maptype: int = 7,
):
    """sites are (planet_id, x, y, owner_id, league_team_id). owner_id 0 is unowned."""
    turn = load_sample_turn()
    planet_template = turn.planets[0]
    player_template = turn.players[0]
    planets = []
    players_by_id: dict[int, Player] = {}
    for planet_id, x, y, owner_id, league_team_id in sites:
        planets.append(_planet(planet_template, planet_id=planet_id, x=x, y=y, ownerid=owner_id))
        if owner_id != 0 and owner_id not in players_by_id:
            players_by_id[owner_id] = _roster_player(
                player_template,
                player_id=owner_id,
                league_team_id=league_team_id,
            )
    players = [players_by_id[player_id] for player_id in sorted(players_by_id)]
    return replace(
        turn,
        planets=planets,
        players=players,
        player=players[0],
        settings=replace(
            turn.settings,
            sphere=sphere,
            mapwidth=width,
            mapheight=height,
            mapshape=mapshape,
        ),
        game=replace(turn.game, maptype=maptype),
    )


def _rings(overlay: dict) -> list[tuple[float, float]]:
    return [(vertex["x"], vertex["y"]) for vertex in overlay["geometry"]["vertices"]]


def _contains(vertices: list[tuple[float, float]], x: float, y: float) -> bool:
    """Even-odd containment. A bridged hole stays outside the filled component."""
    inside = False
    count = len(vertices)
    previous = count - 1
    for index in range(count):
        x1, y1 = vertices[index]
        x0, y0 = vertices[previous]
        if (y1 > y) != (y0 > y):
            crossing_x = (x0 - x1) * (y - y1) / (y0 - y1) + x1
            if x < crossing_x:
                inside = not inside
        previous = index
    return inside


def _teams_at(payload: dict, kind: str, x: float, y: float) -> set[int]:
    found: set[int] = set()
    for overlay in payload["regionOverlays"]:
        if overlay["kind"] != kind:
            continue
        if _contains(_rings(overlay), x, y):
            found.add(overlay["leagueTeamId"])
    return found


def _assert_boundary_wire(payload: dict, *, width: int, height: int) -> None:
    assert payload["analyticId"] == ANALYTIC_ID
    for overlay in payload["regionOverlays"]:
        assert overlay["fillOpacity"] == 0.35
        assert isinstance(overlay["leagueTeamId"], int)
        assert "name" not in overlay
        assert "label" not in overlay
        geometry = overlay["geometry"]
        assert geometry["type"] == "boundary"
        vertices = geometry["vertices"]
        assert len(vertices) >= 3
        assert geometry["edges"] == [{"type": "line"}] * len(vertices)
        for vertex in vertices:
            assert 0 <= vertex["x"] <= width
            assert 0 <= vertex["y"] <= height
        assert overlay["id"].startswith(f"{overlay['kind']}:{overlay['leagueTeamId']}:")


def test_catalog_registers_map_only_team_information() -> None:
    entry = catalog_entry(ANALYTIC_ID)
    assert entry.name == "Team information"
    assert entry.supports_table is False
    assert entry.supports_map is True
    assert entry.type == "selectable"
    assert REGISTRATION.catalog_entry == entry
    assert REGISTRATION.export_catalog is not None
    assert REGISTRATION.export_catalog.is_empty is True
    assert REGISTRATION.export_catalog.analytic_id == ANALYTIC_ID


def test_sphere_edge_site_claims_far_side_inside_the_rectangle() -> None:
    width, height = 100, 40
    # Planet 1 sits on the left edge. On a sphere its wrap image is nearer to
    # x = width - 1 than the mid-row planet. Planar distance says the opposite.
    turn = _territory_turn(
        [
            (1, 1, 20, 1, 4),
            (2, 50, 20, 2, 8),
        ],
        sphere=True,
        width=width,
        height=height,
    )
    payload = get_team_information(turn)
    _assert_boundary_wire(payload, width=width, height=height)
    assert payload["sphere"] is True
    assert _teams_at(payload, KIND_ALL, 99, 20) == {4}
    assert _teams_at(payload, KIND_OWNED, 99, 20) == {4}
    assert _teams_at(payload, KIND_ALL, 1, 20) == {4}
    assert _teams_at(payload, KIND_ALL, 50, 20) == {8}
    assert payload["teams"] == [
        {"leagueTeamId": 4, "fillColor": "#fbbf24", "playerIds": [1]},
        {"leagueTeamId": 8, "fillColor": "#f97316", "playerIds": [2]},
    ]
    for overlay in payload["regionOverlays"]:
        if overlay["leagueTeamId"] == 4:
            assert overlay["fillColor"] == "#fbbf24"


def test_non_sphere_edge_site_does_not_claim_the_far_side() -> None:
    width, height = 100, 40
    turn = _territory_turn(
        [
            (1, 1, 20, 1, 4),
            (2, 50, 20, 2, 8),
        ],
        sphere=False,
        width=width,
        height=height,
        mapshape=2,
        maptype=9,
    )
    payload = get_team_information(turn)
    _assert_boundary_wire(payload, width=width, height=height)
    assert payload["sphere"] is False
    assert _teams_at(payload, KIND_ALL, 99, 20) == {8}
    assert _teams_at(payload, KIND_OWNED, 99, 20) == {8}
    assert _teams_at(payload, KIND_ALL, 1, 20) == {4}


def test_unowned_cell_is_absent_until_owned_planets_only() -> None:
    width, height = 40, 10
    turn = _territory_turn(
        [
            (1, 10, 5, 1, 5),
            (2, 30, 5, 0, 0),
        ],
        sphere=False,
        width=width,
        height=height,
    )
    payload = get_team_information(turn)
    _assert_boundary_wire(payload, width=width, height=height)
    assert _teams_at(payload, KIND_ALL, 32, 5) == set()
    assert _teams_at(payload, KIND_ALL, 8, 5) == {5}
    assert _teams_at(payload, KIND_OWNED, 32, 5) == {5}
    assert _teams_at(payload, KIND_OWNED, 8, 5) == {5}


def test_player_without_league_team_is_absent_from_both_site_sets() -> None:
    width, height = 40, 10
    turn = _territory_turn(
        [
            (1, 10, 5, 1, 0),
            (2, 30, 5, 2, 7),
        ],
        sphere=False,
        width=width,
        height=height,
    )
    payload = get_team_information(turn)
    _assert_boundary_wire(payload, width=width, height=height)
    assert _teams_at(payload, KIND_ALL, 8, 5) == set()
    assert _teams_at(payload, KIND_OWNED, 8, 5) == set()
    assert _teams_at(payload, KIND_ALL, 32, 5) == {7}
    assert _teams_at(payload, KIND_OWNED, 32, 5) == {7}
    assert payload["teams"] == [
        {"leagueTeamId": 7, "fillColor": "#a3e635", "playerIds": [2]},
    ]


def test_bordering_planets_on_one_league_team_union_into_one_component() -> None:
    width, height = 40, 20
    turn = _territory_turn(
        [
            (1, 10, 10, 1, 4),
            (2, 20, 10, 2, 4),
        ],
        sphere=False,
        width=width,
        height=height,
    )
    payload = get_team_information(turn)
    _assert_boundary_wire(payload, width=width, height=height)
    same_team = [overlay for overlay in payload["regionOverlays"] if overlay["kind"] == KIND_ALL]
    assert len(same_team) == 1
    assert same_team[0]["leagueTeamId"] == 4
    assert same_team[0]["id"] == "team-territory:4:0"
    ring = _rings(same_team[0])
    assert _contains(ring, 1, 1)
    assert _contains(ring, 39, 19)
    assert payload["teams"] == [
        {"leagueTeamId": 4, "fillColor": "#fbbf24", "playerIds": [1, 2]},
    ]


def test_exact_tie_lower_planet_id_wins() -> None:
    width, height = 30, 20
    turn = _territory_turn(
        [
            (1, 15, 10, 1, 2),
            (2, 15, 10, 2, 9),
        ],
        sphere=False,
        width=width,
        height=height,
    )
    payload = get_team_information(turn)
    _assert_boundary_wire(payload, width=width, height=height)
    assert _teams_at(payload, KIND_ALL, 1, 1) == {2}
    assert _teams_at(payload, KIND_OWNED, 1, 1) == {2}
    assert all(overlay["leagueTeamId"] != 9 for overlay in payload["regionOverlays"])
    assert {team["leagueTeamId"] for team in payload["teams"]} == {2, 9}


def test_surrounded_team_is_a_hole_in_one_component() -> None:
    width, height = 100, 100
    turn = _territory_turn(
        [
            (1, 10, 10, 1, 3),
            (2, 10, 90, 1, 3),
            (3, 90, 10, 1, 3),
            (4, 90, 90, 1, 3),
            (5, 50, 50, 2, 8),
        ],
        sphere=False,
        width=width,
        height=height,
    )
    payload = get_team_information(turn)
    _assert_boundary_wire(payload, width=width, height=height)
    frame = [
        overlay
        for overlay in payload["regionOverlays"]
        if overlay["kind"] == KIND_ALL and overlay["leagueTeamId"] == 3
    ]
    assert len(frame) == 1
    ring = _rings(frame[0])
    assert _contains(ring, 2, 50)
    assert not _contains(ring, 50, 50)
    assert _teams_at(payload, KIND_ALL, 50, 50) == {8}


def test_two_holes_on_one_row_are_both_cut_into_one_component() -> None:
    width, height = 100, 100
    frame = [
        (planet_id, x, y, 1, 3)
        for planet_id, (x, y) in enumerate(
            [
                (10, 10),
                (50, 10),
                (90, 10),
                (10, 50),
                (50, 50),
                (90, 50),
                (10, 90),
                (50, 90),
                (90, 90),
            ],
            start=1,
        )
    ]
    turn = _territory_turn(
        [*frame, (10, 30, 50, 2, 8), (11, 70, 50, 2, 8)],
        sphere=False,
        width=width,
        height=height,
    )
    payload = get_team_information(turn)
    _assert_boundary_wire(payload, width=width, height=height)
    frame_overlays = [
        overlay
        for overlay in payload["regionOverlays"]
        if overlay["kind"] == KIND_ALL and overlay["leagueTeamId"] == 3
    ]
    assert len(frame_overlays) == 1
    ring = _rings(frame_overlays[0])
    assert _contains(ring, 50, 50)
    assert not _contains(ring, 30, 50)
    assert not _contains(ring, 70, 50)
    assert _teams_at(payload, KIND_ALL, 30, 50) == {8}
    assert _teams_at(payload, KIND_ALL, 70, 50) == {8}


def _surrounded_sites() -> list[TerritorySite]:
    return [
        TerritorySite(planet_id=1, x=10, y=10, league_team_id=3),
        TerritorySite(planet_id=2, x=10, y=90, league_team_id=3),
        TerritorySite(planet_id=3, x=90, y=10, league_team_id=3),
        TerritorySite(planet_id=4, x=90, y=90, league_team_id=3),
        TerritorySite(planet_id=5, x=50, y=50, league_team_id=8),
    ]


def test_hole_cut_that_fills_the_hole_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(team_territory, "_splice_hole", lambda ring, hole: ring)
    with pytest.raises(TerritoryRingError):
        territory_components(_surrounded_sites(), width=100, height=100, sphere=False)


def test_hole_cut_without_a_boundary_edge_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(team_territory, "_splice_hole", lambda ring, hole: None)
    with pytest.raises(TerritoryRingError):
        territory_components(_surrounded_sites(), width=100, height=100, sphere=False)
