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


def table_from_core(core_data: dict) -> dict:
    """Shape Core fleet compute output for GET /bff/analytics/fleet/table."""
    return {
        "analyticId": ANALYTIC_ID,
        "defaultActiveOnly": True,
        "players": [
            _shape_table_player(player)
            for player in core_data.get("players", [])
            if isinstance(player, dict)
        ],
    }


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
    core_data = load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)
    return table_from_core(core_data)


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
