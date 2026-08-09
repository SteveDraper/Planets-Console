"""SPA fleet table wire shaping shared by the BFF table route and NDJSON stream."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipRecord
    from api.models.components import Hull
    from api.models.game import TurnInfo
    from api.models.ship import Ship


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


def fleet_ship_record_to_table_wire(
    record: FleetShipRecord,
    *,
    turn: TurnInfo,
    ships_by_id: Mapping[int, Ship] | None = None,
    hulls_by_id_map: Mapping[int, Hull] | None = None,
) -> dict[str, object]:
    """Shape one ship record for the SPA table wire (no evidence events).

    Optional ``ships_by_id`` / ``hulls_by_id_map`` are forwarded to motion
    shaping so ledger callers can build indexes once.
    """
    from api.analytics.fleet.military_estimate import fleet_ship_military_estimate_2x
    from api.analytics.fleet.motion_estimate import fleet_ship_motion_wire
    from api.analytics.fleet.serialization import fleet_ship_record_to_json

    shaped = _strip_ship_record_dict(fleet_ship_record_to_json(record))
    estimate = fleet_ship_military_estimate_2x(record, turn=turn)
    if estimate is not None:
        shaped["militaryEstimate2x"] = estimate
    motion = fleet_ship_motion_wire(
        record,
        turn=turn,
        ships_by_id=ships_by_id,
        hulls_by_id_map=hulls_by_id_map,
    )
    if motion is not None:
        shaped["motion"] = motion
    return shaped


def fleet_acquisition_ledger_to_table_wire(
    ledger: FleetAcquisitionLedger,
    *,
    turn: TurnInfo,
) -> dict[str, object]:
    """Shape one player ledger for the SPA table wire."""
    from api.analytics.fleet.serialization import fleet_count_discrepancy_to_json
    from api.concepts.turn_component_catalog import hulls_by_id

    ships_by_id = {ship.id: ship for ship in turn.ships}
    hulls_by_id_map = hulls_by_id(turn)
    shaped: dict[str, object] = {
        "playerId": ledger.player_id,
        "playerName": ledger.player_name,
        "records": [
            fleet_ship_record_to_table_wire(
                record,
                turn=turn,
                ships_by_id=ships_by_id,
                hulls_by_id_map=hulls_by_id_map,
            )
            for record in ledger.records
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
