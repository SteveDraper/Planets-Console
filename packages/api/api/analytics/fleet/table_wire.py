"""SPA fleet table wire shaping shared by the BFF table route and NDJSON stream."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipRecord


def fleet_ship_record_to_table_wire_json(record: dict[str, object]) -> dict[str, object]:
    """Shape one core ship record dict for the SPA table wire (no evidence events)."""
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


def fleet_ship_record_to_table_wire(record: FleetShipRecord) -> dict[str, object]:
    """Shape one ship record for the SPA table wire (no evidence events)."""
    from api.analytics.fleet.serialization import fleet_ship_record_to_json

    return fleet_ship_record_to_table_wire_json(fleet_ship_record_to_json(record))


def fleet_acquisition_ledger_to_table_wire(ledger: FleetAcquisitionLedger) -> dict[str, object]:
    """Shape one player ledger for the SPA table wire."""
    from api.analytics.fleet.serialization import fleet_acquisition_ledger_to_json

    return fleet_acquisition_ledger_to_table_wire_json(fleet_acquisition_ledger_to_json(ledger))


def fleet_acquisition_ledger_to_table_wire_json(player: dict[str, object]) -> dict[str, object]:
    """Shape one core player ledger dict for the SPA table wire."""
    shaped: dict[str, object] = {
        "playerId": player.get("playerId"),
        "playerName": player.get("playerName", ""),
        "records": [
            fleet_ship_record_to_table_wire_json(record)
            for record in player.get("records", [])
            if isinstance(record, dict)
        ],
    }
    discrepancy = player.get("discrepancy")
    if discrepancy is not None:
        shaped["discrepancy"] = discrepancy
    return shaped
