"""Territory analytic: paint the nearest-planet partition by player or by league team."""

from __future__ import annotations

from collections import defaultdict

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.analytics.team_palette import TeamStyle, assign_team_styles
from api.analytics.team_territory import (
    PLAYER_TERRITORY_KINDS,
    TerritorySection,
    league_team_id_by_player,
    territory_sections_with_neighbors,
)
from api.concepts.map_region_coverage import (
    MapRegionBoundaryLineEdge,
    MapRegionOverlayVertex,
    boundary_to_overlay,
    map_region_overlay_to_wire,
)
from api.models.game import TurnInfo

ANALYTIC_ID = "team-information"
FILL_OPACITY = 0.35
# Present on the wire so the overlay shape stays shared. The SPA replaces it
# with the per-player palette at paint time.
PLAYER_TERRITORY_FILL_COLOR = "#000000"
PLAYER_TERRITORY_FILL_PATTERN = "solid"


def _team_rows(
    turn: TurnInfo,
    league_team_by_player: dict[int, int],
    styles: dict[int, TeamStyle],
) -> list[dict]:
    """League teams that own at least one planet, with the full roster of that id."""
    teams_with_planets: set[int] = set()
    for planet in turn.planets:
        if planet.ownerid == 0:
            continue
        league_team_id = league_team_by_player.get(planet.ownerid, 0)
        if league_team_id > 0:
            teams_with_planets.add(league_team_id)
    roster: dict[int, set[int]] = defaultdict(set)
    for player_id, league_team_id in league_team_by_player.items():
        if league_team_id > 0:
            roster[league_team_id].add(player_id)
    return [
        {
            "leagueTeamId": league_team_id,
            "fillColor": styles[league_team_id].fill_color,
            "fillPattern": styles[league_team_id].fill_pattern,
            "playerIds": sorted(roster[league_team_id]),
        }
        for league_team_id in sorted(teams_with_planets)
    ]


def _boundary_overlay(
    *,
    kind: str,
    group_id: int,
    component: int,
    ring: list[tuple[float, float]],
    styles: dict[int, TeamStyle],
) -> dict:
    """Player kinds carry a player id and a placeholder fill; other kinds carry a league team."""
    if kind in PLAYER_TERRITORY_KINDS:
        fill_color = PLAYER_TERRITORY_FILL_COLOR
        fill_pattern = PLAYER_TERRITORY_FILL_PATTERN
        owner_field = "playerId"
    else:
        style = styles[group_id]
        fill_color = style.fill_color
        fill_pattern = style.fill_pattern
        owner_field = "leagueTeamId"
    overlay = boundary_to_overlay(
        kind=kind,
        overlay_id=f"{kind}:{group_id}:{component}",
        fill_color=fill_color,
        fill_opacity=FILL_OPACITY,
        vertices=[MapRegionOverlayVertex(x=x, y=y) for x, y in ring],
        edges=[MapRegionBoundaryLineEdge() for _ in ring],
        fill_pattern=fill_pattern,
    )
    wire = map_region_overlay_to_wire(overlay)
    wire[owner_field] = group_id
    return wire


def _player_rows(turn: TurnInfo) -> list[dict]:
    """Players who own at least one planet, including those with no league team."""
    owner_ids = {planet.ownerid for planet in turn.planets if planet.ownerid != 0}
    return [{"playerId": player_id} for player_id in sorted(owner_ids)]


def _region_overlays(
    partitions: list[TerritorySection],
    styles: dict[int, TeamStyle],
) -> list[dict]:
    overlays: list[dict] = []
    for kind, components in partitions:
        grouped: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
        for group_id, ring in components:
            grouped[group_id].append(ring)
        for group_id in sorted(grouped):
            for component, ring in enumerate(grouped[group_id]):
                overlays.append(
                    _boundary_overlay(
                        kind=kind,
                        group_id=group_id,
                        component=component,
                        ring=ring,
                        styles=styles,
                    )
                )
    return overlays


def _styles_for_turn(
    turn: TurnInfo,
    league_team_by_player: dict[int, int],
    neighbors: dict[int, set[int]],
) -> dict[int, TeamStyle]:
    teams_with_planets: set[int] = set()
    for planet in turn.planets:
        if planet.ownerid == 0:
            continue
        league_team_id = league_team_by_player.get(planet.ownerid, 0)
        if league_team_id > 0:
            teams_with_planets.add(league_team_id)
    return assign_team_styles(teams_with_planets, neighbors)


def compute_team_information(ctx: AnalyticComputeContext) -> dict:
    """Return player and league-team partitions for both site sets."""
    turn = ctx.turn
    league_team_by_player = league_team_id_by_player(turn)
    partitions, neighbors = territory_sections_with_neighbors(turn)
    styles = _styles_for_turn(turn, league_team_by_player, neighbors)
    return {
        "analyticId": ANALYTIC_ID,
        "sphere": turn.settings.sphere,
        "teams": _team_rows(turn, league_team_by_player, styles),
        "players": _player_rows(turn),
        "regionOverlays": _region_overlays(partitions, styles),
    }


def get_team_information(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
) -> dict:
    """Convenience entry for tests and direct callers."""
    return invoke_analytic_compute(
        compute_team_information,
        turn,
        options,
        game_id=turn.game.id,
        perspective=turn.player.id,
    )


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_team_information,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)
