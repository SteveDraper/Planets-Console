"""SPA fleet table wire shaping shared by the BFF table route and NDJSON stream."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipRecord
    from api.models.game import TurnInfo


def _strip_ship_record_dict(record: dict[str, object]) -> dict[str, object]:
    """Copy SPA table fields from a core record dict (no evidence events, no estimates)."""
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


def strip_fleet_ship_record_for_table_wire(record: dict[str, object]) -> dict[str, object]:
    """Strip core-only fields for table wire without attaching military estimates."""
    return _strip_ship_record_dict(record)


def strip_fleet_acquisition_ledger_for_table_wire(
    player: dict[str, object],
) -> dict[str, object]:
    """Strip one core player ledger dict for table wire without military estimates."""
    shaped: dict[str, object] = {
        "playerId": player.get("playerId"),
        "playerName": player.get("playerName", ""),
        "records": [
            strip_fleet_ship_record_for_table_wire(record)
            for record in player.get("records", [])
            if isinstance(record, dict)
        ],
    }
    discrepancy = player.get("discrepancy")
    if discrepancy is not None:
        shaped["discrepancy"] = discrepancy
    return shaped


def fleet_ship_record_to_table_wire_json(
    record: dict[str, object],
    *,
    turn: TurnInfo,
) -> dict[str, object]:
    """Shape one core ship record dict for the SPA table wire (no evidence events)."""
    from api.analytics.fleet.serialization import fleet_ship_record_from_json

    return fleet_ship_record_to_table_wire(
        fleet_ship_record_from_json(record),
        turn=turn,
    )


def fleet_ship_record_to_table_wire(
    record: FleetShipRecord,
    *,
    turn: TurnInfo,
) -> dict[str, object]:
    """Shape one ship record for the SPA table wire (no evidence events)."""
    from api.analytics.fleet.military_estimate import fleet_ship_military_estimate_2x
    from api.analytics.fleet.serialization import fleet_ship_record_to_json

    shaped = _strip_ship_record_dict(fleet_ship_record_to_json(record))
    estimate = fleet_ship_military_estimate_2x(record, turn=turn)
    if estimate is not None:
        shaped["militaryEstimate2x"] = estimate
    return shaped


def fleet_acquisition_ledger_to_table_wire(
    ledger: FleetAcquisitionLedger,
    *,
    turn: TurnInfo,
) -> dict[str, object]:
    """Shape one player ledger for the SPA table wire."""
    from api.analytics.fleet.serialization import fleet_count_discrepancy_to_json

    shaped: dict[str, object] = {
        "playerId": ledger.player_id,
        "playerName": ledger.player_name,
        "records": [
            fleet_ship_record_to_table_wire(record, turn=turn) for record in ledger.records
        ],
    }
    if ledger.discrepancy is not None:
        shaped["discrepancy"] = fleet_count_discrepancy_to_json(ledger.discrepancy)
    return shaped


def fleet_acquisition_ledger_to_table_wire_json(
    player: dict[str, object],
    *,
    turn: TurnInfo,
) -> dict[str, object]:
    """Shape one core player ledger dict for the SPA table wire."""
    from api.analytics.fleet.serialization import fleet_acquisition_ledger_from_json

    return fleet_acquisition_ledger_to_table_wire(
        fleet_acquisition_ledger_from_json(player),
        turn=turn,
    )
