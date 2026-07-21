"""Per-record ship id bound tightening for fleet ledgers."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetEvidenceEvent,
    FleetFieldBounded,
    FleetFieldKnown,
    FleetShipRecord,
)
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.fleet.turn_context import FleetTurnContext

SCOREBOARD_SOURCE = "scoreboard"


def tighten_inferred_ship_id_bounds_if_computable(
    ledger: FleetAcquisitionLedger,
    turn_context: FleetTurnContext,
) -> None:
    """Tighten id bounds when a max ship-id bound is computable for the shell turn."""
    if turn_context.max_ship_id_bound is None:
        return
    tighten_inferred_ship_id_bounds(
        ledger,
        turn_context.turn,
        shell_turn=turn_context.turn.settings.turn,
    )


def tighten_inferred_ship_id_bounds(
    ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
    *,
    shell_turn: int,
) -> None:
    """Apply host-turn-appropriate id bounds to inferred rows on this shell turn."""
    from api.analytics.fleet.scoreboard_counts import max_ship_id_bound_for_inferred_record

    for record in ledger.records:
        if record.disposition != "active":
            continue
        if isinstance(record.fields.ship_id, FleetFieldKnown):
            continue
        event = _scoreboard_acquisition_event(record, shell_turn)
        if event is None:
            continue
        max_bound = max_ship_id_bound_for_inferred_record(
            turn,
            shell_turn=shell_turn,
            built_turn=_known_built_turn(record),
            is_starting_inventory=_is_homeworld_starting_inventory_event(event),
        )
        if max_bound is None:
            continue
        _apply_ship_id_bound(record, max_bound, shell_turn=shell_turn)


def _apply_ship_id_bound(
    record: FleetShipRecord,
    max_bound: int,
    *,
    shell_turn: int,
) -> None:
    tightened = FleetFieldBounded(operator="lte", value=max_bound)
    if record.fields.ship_id == tightened:
        return
    if isinstance(record.fields.ship_id, FleetFieldBounded):
        if record.fields.ship_id.operator == "lte" and record.fields.ship_id.value <= max_bound:
            return
    record.fields.ship_id = tightened
    append_fleet_evidence_event(
        record,
        FleetEvidenceEvent(
            event_id=str(uuid.uuid4()),
            kind="id_bound_tightened",
            turn=shell_turn,
            source=SCOREBOARD_SOURCE,
            payload={"maxShipId": max_bound},
        ),
    )


def _known_built_turn(record: FleetShipRecord) -> int | None:
    built_turn = record.fields.built_turn
    if isinstance(built_turn, FleetFieldKnown) and isinstance(built_turn.value, int):
        return built_turn.value
    return None


def _scoreboard_acquisition_event(
    record: FleetShipRecord,
    shell_turn: int,
) -> FleetEvidenceEvent | None:
    for event in record.events:
        if event.kind != "scoreboard_delta" or event.turn != shell_turn:
            continue
        if _is_homeworld_starting_inventory_event(event):
            return event
        warship_delta = event.payload.get("warshipDelta", 0)
        freighter_delta = event.payload.get("freighterDelta", 0)
        if not isinstance(warship_delta, int) or isinstance(warship_delta, bool):
            continue
        if not isinstance(freighter_delta, int) or isinstance(freighter_delta, bool):
            continue
        if warship_delta > 0 or freighter_delta > 0:
            return event
    return None


def _is_homeworld_starting_inventory_event(event: FleetEvidenceEvent) -> bool:
    return event.payload.get("homeworldStartingInventory") is True
