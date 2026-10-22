"""Territory movie payload: grid, legend, and stored-turn span."""

from __future__ import annotations

import base64
import gzip
import json
import struct
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics.team_territory import (
    TERRITORY_SECTION_KINDS,
    nu_map_rectangle,
    territory_sections,
)
from api.analytics.territory_movie import build_territory_movie, quantize_offset
from api.compute.turn_cache import clear_process_turn_info_cache
from api.config import ApiConfig, set_config
from api.errors import UpstreamPlanetsError, ValidationError
from api.planets_nu import PlanetsNuClient
from api.serialization.game import game_info_from_json, game_info_to_json
from api.serialization.turn import turn_info_to_json
from api.services.turn_load_service import TurnLoadService
from api.storage_factory import clear_backend_cache, get_storage
from fastapi.testclient import TestClient

from tests.team_territory_turns import territory_turn

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
_WIDTH = 100
_HEIGHT = 40
_PERSPECTIVE = 1


def _inflate(blob: str) -> bytes:
    return gzip.decompress(base64.b64decode(blob))


def _words(payload: bytes) -> list[int]:
    assert len(payload) % 2 == 0
    return list(struct.unpack(f"<{len(payload) // 2}H", payload))


def _parse_rings(
    payload: bytes, turn_count: int
) -> dict[str, list[list[tuple[int, list[tuple[int, int]]]]]]:
    words = _words(payload)
    index = 0

    def take() -> int:
        nonlocal index
        value = words[index]
        index += 1
        return value

    parsed: dict[str, list[list[tuple[int, list[tuple[int, int]]]]]] = {}
    for kind in TERRITORY_SECTION_KINDS:
        turns: list[list[tuple[int, list[tuple[int, int]]]]] = []
        for _turn_index in range(turn_count):
            components: list[tuple[int, list[tuple[int, int]]]] = []
            for _component in range(take()):
                group_id = take()
                vertices = [(take(), take()) for _vertex in range(take())]
                components.append((group_id, vertices))
            turns.append(components)
        parsed[kind] = turns
    assert index == len(words)
    return parsed


def _parse_planets(payload: bytes) -> list[tuple[int, int, int, int]]:
    words = _words(payload)
    count = words[0]
    assert len(words) == 1 + count * 4
    rows = []
    for index in range(count):
        base = 1 + index * 4
        rows.append((words[base], words[base + 1], words[base + 2], words[base + 3]))
    return rows


def _turn(
    sites: list[tuple[int, int, int, int, int]],
    *,
    host_turn: int,
    width: int = _WIDTH,
    height: int = _HEIGHT,
):
    return territory_turn(
        sites,
        sphere=False,
        width=width,
        height=height,
        host_turn=host_turn,
    )


def test_grid_quantizes_with_python_round_ties_to_even() -> None:
    origin = 1000.0
    # These offsets are dyadic, so the tenth-LY value is an exact n + 0.5.
    assert quantize_offset(origin + 0.25, origin) == 2
    assert quantize_offset(origin + 0.75, origin) == 8
    assert quantize_offset(origin + 1.25, origin) == 12
    assert quantize_offset(origin + 1.75, origin) == 18


def test_vertices_match_tenth_light_year_grid() -> None:
    turn = _turn([(1, 10, 20, 1, 4), (2, 70, 20, 2, 8)], host_turn=1)
    movie = build_territory_movie([turn], player_names={}, team_names={})
    rectangle = nu_map_rectangle(_WIDTH, _HEIGHT)
    assert movie.rectangle.left == rectangle.left
    assert movie.rectangle.bottom == rectangle.bottom
    assert movie.rectangle.width == rectangle.width
    assert movie.rectangle.height == rectangle.height
    assert movie.turn == 1
    packed = _parse_rings(_inflate(movie.rings), 1)
    sections = dict(territory_sections(turn))
    for kind in TERRITORY_SECTION_KINDS:
        assert len(packed[kind]) == 1
        decoded = packed[kind][0]
        assert len(decoded) == len(sections[kind])
        for (group_id, ring), (packed_id, vertices) in zip(sections[kind], decoded, strict=True):
            assert packed_id == group_id
            assert group_id > 0
            for (x, y), (dx, dy) in zip(ring, vertices, strict=True):
                assert dx == quantize_offset(x, rectangle.left)
                assert dy == quantize_offset(y, rectangle.bottom)


def test_empty_team_section_is_a_zero_count_for_every_turn() -> None:
    sites = [(1, 10, 20, 1, 0), (2, 80, 20, 2, 0)]
    turns = [_turn(sites, host_turn=1), _turn(sites, host_turn=2)]
    movie = build_territory_movie(turns, player_names={}, team_names={})
    packed = _parse_rings(_inflate(movie.rings), 2)
    assert packed["team-territory"] == [[], []]
    assert packed["team-territory-owned-only"] == [[], []]
    assert packed["player-territory"][0]
    assert packed["player-territory"][1]


def test_group_id_zero_is_omitted() -> None:
    turn = _turn(
        [
            (1, 10, 20, 0, 0),
            (2, 90, 20, 4, 0),
            (3, 50, 20, 5, 9),
        ],
        host_turn=1,
    )
    movie = build_territory_movie([turn], player_names={}, team_names={})
    packed = _parse_rings(_inflate(movie.rings), 1)
    for kind in ("team-territory", "team-territory-owned-only"):
        assert {group_id for group_id, _ring in packed[kind][0]} == {9}
    for kind in ("player-territory", "player-territory-owned-only"):
        assert {group_id for group_id, _ring in packed[kind][0]} == {4, 5}


def test_owned_planets_only_is_a_second_diagram() -> None:
    turn = _turn(
        [
            (1, 10, 20, 1, 4),
            (2, 50, 20, 0, 0),
            (3, 90, 20, 2, 8),
        ],
        host_turn=1,
    )
    movie = build_territory_movie([turn], player_names={}, team_names={})
    packed = _parse_rings(_inflate(movie.rings), 1)
    assert packed["player-territory"] != packed["player-territory-owned-only"]
    assert packed["team-territory"] != packed["team-territory-owned-only"]


def test_planet_that_appears_after_turn_one_keeps_that_first_turn() -> None:
    turn_1 = _turn([(2, 10, 20, 1, 0), (1, 80, 20, 1, 0)], host_turn=1)
    turn_2 = _turn(
        [(2, 10, 20, 1, 0), (1, 80, 20, 1, 0), (5, 50, 30, 2, 0)],
        host_turn=2,
    )
    movie = build_territory_movie([turn_1, turn_2], player_names={1: "Ada", 2: "  "}, team_names={})
    rows = _parse_planets(_inflate(movie.planets))
    assert [row[0] for row in rows] == [1, 2, 5]
    by_id = {row[0]: row for row in rows}
    first = {planet.id: planet for planet in turn_1.planets}
    late = next(planet for planet in turn_2.planets if planet.id == 5)
    assert by_id[1] == (1, first[1].x, first[1].y, 1)
    assert by_id[2] == (2, first[2].x, first[2].y, 1)
    assert by_id[5] == (5, late.x, late.y, 2)
    assert [(entry.id, entry.name) for entry in movie.players] == [(1, "Ada"), (2, None)]
    assert movie.teams == []
    assert movie.turn == 2


def test_span_must_be_host_turns_from_one() -> None:
    turn = _turn([(1, 10, 20, 1, 0)], host_turn=2)
    with pytest.raises(ValidationError, match="no gaps"):
        build_territory_movie([turn], player_names={}, team_names={})


def test_turns_must_share_one_map_rectangle() -> None:
    first = _turn([(1, 10, 20, 1, 0)], host_turn=1)
    second = _turn([(1, 10, 20, 1, 0)], host_turn=2, width=120)
    with pytest.raises(ValidationError, match="map rectangle"):
        build_territory_movie([first, second], player_names={}, team_names={})


@pytest.fixture
def client():
    clear_backend_cache()
    clear_process_turn_info_cache()
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    from api.app import app

    yield TestClient(app, raise_server_exceptions=False)
    clear_process_turn_info_cache()
    clear_backend_cache()


def _store_span(
    turns,
    *,
    game_turn: int,
    roster_names: dict[int, str] | None = None,
    blank_turn_player_ids: set[int] | None = None,
) -> int:
    roster_names = roster_names or {}
    blank_turn_player_ids = blank_turn_player_ids or set()
    stored_turns = []
    for turn in turns:
        players = [
            replace(player, username="") if player.id in blank_turn_player_ids else player
            for player in turn.players
        ]
        viewpoint = next(player for player in players if player.id == turn.player.id)
        stored_turns.append(replace(turn, players=players, player=viewpoint))
    roster = []
    seen: set[int] = set()
    for turn in stored_turns:
        for player in turn.players:
            if player.id in seen:
                continue
            seen.add(player.id)
            username = roster_names.get(player.id, player.username)
            roster.append(replace(player, username=username))
    info = game_info_from_json(json.loads((ASSETS_DIR / "game_info_sample.json").read_text()))
    game_id = stored_turns[0].game.id
    info = replace(
        info,
        game=replace(info.game, id=game_id, turn=game_turn),
        players=roster,
    )
    storage = get_storage()
    storage.put(f"games/{game_id}/info", game_info_to_json(info))
    for turn in stored_turns:
        storage.put(
            TurnLoadService.turn_store_key(game_id, _PERSPECTIVE, turn.settings.turn),
            turn_info_to_json(turn),
        )
    return game_id


def test_route_legend_uses_roster_and_directory_names(client) -> None:
    turn = _turn(
        [
            (1, 10, 20, 1, 9),
            (2, 90, 20, 2, 8),
        ],
        host_turn=1,
    )
    game_id = _store_span(
        [turn],
        game_turn=1,
        roster_names={1: "Ada", 2: ""},
        blank_turn_player_ids={2},
    )
    get_storage().put("league-teams/9", {"id": 9, "name": "Hawks"})

    def _fail(self, username: str) -> dict:
        raise UpstreamPlanetsError("Planets.nu load profile request failed.")

    with patch.object(PlanetsNuClient, "load_profile", _fail):
        response = client.get(f"/v1/games/{game_id}/{_PERSPECTIVE}/territory-movie")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"turn", "rectangle", "rings", "planets", "players", "teams"}
    assert body["turn"] == 1
    assert body["players"] == [{"id": 1, "name": "Ada"}, {"id": 2, "name": None}]
    assert body["teams"] == [{"id": 8, "name": None}, {"id": 9, "name": "Hawks"}]
    assert "fillColor" not in body
    _parse_rings(_inflate(body["rings"]), 1)


def test_missing_stored_turn_fails_the_request(client) -> None:
    turn_1 = _turn([(1, 10, 20, 1, 0)], host_turn=1)
    turn_3 = _turn([(1, 10, 20, 1, 0)], host_turn=3)
    game_id = _store_span([turn_1, turn_3], game_turn=3)
    response = client.get(f"/v1/games/{game_id}/{_PERSPECTIVE}/territory-movie")
    assert response.status_code == 404
    assert response.json()["detail"] == (
        f"Stored turn 2 is missing for game {game_id} perspective {_PERSPECTIVE}."
    )


def test_game_with_no_host_turn_is_rejected(client) -> None:
    info = game_info_from_json(json.loads((ASSETS_DIR / "game_info_sample.json").read_text()))
    info = replace(info, game=replace(info.game, turn=0))
    get_storage().put(f"games/{info.game.id}/info", game_info_to_json(info))
    response = client.get(f"/v1/games/{info.game.id}/{_PERSPECTIVE}/territory-movie")
    assert response.status_code == 422
    assert "no host turn" in response.json()["detail"]
