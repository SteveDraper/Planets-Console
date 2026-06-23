"""BFF Fleet analytic handlers."""

from api.analytics.catalog import catalog_entry
from api.diagnostics import Diagnostics

from bff.analytics.descriptor import AnalyticDescriptor
from bff.analytics.models import (
    ConnectionsMapQuery,
    CoreAnalyticsLoader,
    TurnScope,
    load_core_analytic,
)

ANALYTIC_ID = "fleet"


def map_from_core(core_data: dict) -> dict:
    players: list[dict[str, object]] = []
    for player in core_data.get("players", []):
        if not isinstance(player, dict):
            continue
        players.append(
            {
                "playerId": player.get("playerId"),
                "nodes": [],
                "overlayCircles": [],
            }
        )
    return {
        "analyticId": ANALYTIC_ID,
        "players": players,
    }


def get_table(
    scope: TurnScope,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    return load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)


def get_map(
    scope: TurnScope,
    _query: ConnectionsMapQuery,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    core_data = load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)
    return map_from_core(core_data)


DESCRIPTOR = AnalyticDescriptor.from_catalog_entry(
    catalog_entry(ANALYTIC_ID),
    get_table=get_table,
    get_map=get_map,
)
