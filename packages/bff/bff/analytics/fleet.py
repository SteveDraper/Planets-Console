"""BFF Fleet analytic handlers."""

from api.analytics.catalog import catalog_entry
from api.analytics.fleet.table_wire import fleet_acquisition_ledger_to_table_wire_json
from api.diagnostics import Diagnostics
from api.models.game import TurnInfo

from bff.analytics.descriptor import AnalyticDescriptor
from bff.analytics.models import (
    ConnectionsMapQuery,
    CoreAnalyticsLoader,
    TurnScope,
    load_core_analytic,
)

ANALYTIC_ID = "fleet"


def _shape_table_player(player: dict[str, object]) -> dict[str, object]:
    return fleet_acquisition_ledger_to_table_wire_json(player)


def component_catalog_wire(turn: TurnInfo) -> dict[str, dict[str, str]]:
    """Host component id -> display name tables for fleet table rendering."""
    return {
        "hulls": {str(hull.id): hull.name for hull in turn.hulls},
        "engines": {str(engine.id): engine.name for engine in turn.engines},
        "beams": {str(beam.id): beam.name for beam in turn.beams},
        "torpedoes": {str(torpedo.id): torpedo.name for torpedo in turn.torpedos},
    }


def table_from_core(
    core_data: dict,
    *,
    component_catalog: dict[str, dict[str, str]] | None = None,
) -> dict:
    """Shape Core fleet compute output for GET /bff/analytics/fleet/table."""
    payload: dict[str, object] = {
        "analyticId": ANALYTIC_ID,
        "defaultActiveOnly": True,
        "players": [
            _shape_table_player(player)
            for player in core_data.get("players", [])
            if isinstance(player, dict)
        ],
    }
    if component_catalog is not None:
        payload["componentCatalog"] = component_catalog
    return payload


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
    from bff.core_client import get_core_client

    core_data = load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)
    turn = get_core_client().get_turn_info(scope.game_id, scope.perspective, scope.turn)
    return table_from_core(core_data, component_catalog=component_catalog_wire(turn))


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
