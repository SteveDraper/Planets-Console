"""BFF Fleet analytic handlers."""

from api.analytics.catalog import catalog_entry
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


def _shape_table_record(record: dict[str, object]) -> dict[str, object]:
    """Shape one core fleet ship record for the SPA table wire (no evidence events)."""
    shaped: dict[str, object] = {
        "recordId": record.get("recordId"),
        "disposition": record.get("disposition", "active"),
    }
    if "qualifiers" in record:
        shaped["qualifiers"] = record["qualifiers"]
    if "fields" in record:
        shaped["fields"] = record["fields"]
    if "buildOptionSets" in record:
        shaped["buildOptionSets"] = record["buildOptionSets"]
    if "displayDefaultOptionSetIndex" in record:
        shaped["displayDefaultOptionSetIndex"] = record["displayDefaultOptionSetIndex"]
    if "lastSeen" in record:
        shaped["lastSeen"] = record["lastSeen"]
    return shaped


def _shape_table_player(player: dict[str, object]) -> dict[str, object]:
    shaped: dict[str, object] = {
        "playerId": player.get("playerId"),
        "playerName": player.get("playerName", ""),
        "records": [
            _shape_table_record(record)
            for record in player.get("records", [])
            if isinstance(record, dict)
        ],
    }
    discrepancy = player.get("discrepancy")
    if discrepancy is not None:
        shaped["discrepancy"] = discrepancy
    return shaped


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
