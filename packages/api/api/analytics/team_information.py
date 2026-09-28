"""Team information analytic: league-team territory on the shell-turn map."""

from __future__ import annotations

from collections import defaultdict

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.analytics.team_territory import TerritorySite, territory_components
from api.concepts.map_region_coverage import (
    MapRegionBoundaryLineEdge,
    MapRegionOverlayVertex,
    boundary_to_overlay,
    map_region_overlay_to_wire,
)
from api.models.game import TurnInfo

ANALYTIC_ID = "team-information"
FILL_OPACITY = 0.35
KIND_ALL_PLANETS = "team-territory"
KIND_OWNED_ONLY = "team-territory-owned-only"

# Index is ``leagueteamid % 12``. Team 0 is not painted.
PALETTE = (
    "#38bdf8",
    "#f472b6",
    "#a78bfa",
    "#34d399",
    "#fbbf24",
    "#fb7185",
    "#22d3ee",
    "#a3e635",
    "#f97316",
    "#818cf8",
    "#2dd4bf",
    "#e879f9",
)

_SITE_SETS = (
    (KIND_ALL_PLANETS, False),
    (KIND_OWNED_ONLY, True),
)


def _fill_color(league_team_id: int) -> str:
    return PALETTE[league_team_id % len(PALETTE)]


def _league_team_by_player(turn: TurnInfo) -> dict[int, int]:
    by_player = {player.id: player.leagueteamid for player in turn.players}
    by_player.setdefault(turn.player.id, turn.player.leagueteamid)
    return by_player


def _team_rows(turn: TurnInfo, league_team_by_player: dict[int, int]) -> list[dict]:
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
            "fillColor": _fill_color(league_team_id),
            "playerIds": sorted(roster[league_team_id]),
        }
        for league_team_id in sorted(teams_with_planets)
    ]


def _sites(
    turn: TurnInfo,
    league_team_by_player: dict[int, int],
    *,
    owned_only: bool,
) -> list[TerritorySite]:
    sites: list[TerritorySite] = []
    for planet in turn.planets:
        if owned_only and planet.ownerid == 0:
            continue
        if planet.ownerid == 0:
            league_team_id = 0
        else:
            league_team_id = league_team_by_player.get(planet.ownerid, 0)
        sites.append(
            TerritorySite(
                planet_id=planet.id,
                x=float(planet.x),
                y=float(planet.y),
                league_team_id=league_team_id,
            )
        )
    return sites


def _boundary_overlay(
    *,
    kind: str,
    league_team_id: int,
    component: int,
    ring: list[tuple[float, float]],
) -> dict:
    overlay = boundary_to_overlay(
        kind=kind,
        overlay_id=f"{kind}:{league_team_id}:{component}",
        fill_color=_fill_color(league_team_id),
        fill_opacity=FILL_OPACITY,
        vertices=[MapRegionOverlayVertex(x=x, y=y) for x, y in ring],
        edges=[MapRegionBoundaryLineEdge() for _ in ring],
    )
    wire = map_region_overlay_to_wire(overlay)
    wire["leagueTeamId"] = league_team_id
    return wire


def _region_overlays(turn: TurnInfo, league_team_by_player: dict[int, int]) -> list[dict]:
    width = turn.settings.mapwidth
    height = turn.settings.mapheight
    sphere = turn.settings.sphere
    overlays: list[dict] = []
    for kind, owned_only in _SITE_SETS:
        grouped: dict[int, list[list[tuple[float, float]]]] = defaultdict(list)
        for league_team_id, ring in territory_components(
            _sites(turn, league_team_by_player, owned_only=owned_only),
            width=width,
            height=height,
            sphere=sphere,
        ):
            grouped[league_team_id].append(ring)
        for league_team_id in sorted(grouped):
            for component, ring in enumerate(grouped[league_team_id]):
                overlays.append(
                    _boundary_overlay(
                        kind=kind,
                        league_team_id=league_team_id,
                        component=component,
                        ring=ring,
                    )
                )
    return overlays


def compute_team_information(ctx: AnalyticComputeContext) -> dict:
    """Return both team-territory partitions for the shell turn."""
    turn = ctx.turn
    league_team_by_player = _league_team_by_player(turn)
    return {
        "analyticId": ANALYTIC_ID,
        "sphere": turn.settings.sphere,
        "teams": _team_rows(turn, league_team_by_player),
        "regionOverlays": _region_overlays(turn, league_team_by_player),
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
