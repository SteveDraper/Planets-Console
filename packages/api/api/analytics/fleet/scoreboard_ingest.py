"""Create inferred acquisition placeholders from scoreboard build deltas."""

from __future__ import annotations

import uuid
from typing import Literal

from api.analytics.fleet.scoreboard_counts import iter_current_turn_scores
from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
)
from api.models.game import TurnInfo

SCOREBOARD_SOURCE = "scoreboard"

FleetShipClass = Literal["warship", "freighter"]


def ingest_turn_scoreboard_acquisitions(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
) -> FleetTurnSnapshot:
    """Create inferred placeholder rows for positive scoreboard warship/freighter deltas."""
    turn_number = turn.settings.turn
    ledgers_by_player_id = {ledger.player_id: ledger for ledger in snapshot.players}

    for score in iter_current_turn_scores(turn):
        ledger = ledgers_by_player_id.get(score.ownerid)
        if ledger is None:
            continue
        warship_builds = max(0, score.shipchange)
        freighter_builds = max(0, score.freighterchange)
        _ensure_placeholder_rows(
            ledger,
            turn_number=turn_number,
            ship_class="warship",
            expected_count=warship_builds,
            warship_delta=warship_builds,
            freighter_delta=0,
        )
        _ensure_placeholder_rows(
            ledger,
            turn_number=turn_number,
            ship_class="freighter",
            expected_count=freighter_builds,
            warship_delta=0,
            freighter_delta=freighter_builds,
        )

    return snapshot


def _ensure_placeholder_rows(
    ledger: FleetAcquisitionLedger,
    *,
    turn_number: int,
    ship_class: FleetShipClass,
    expected_count: int,
    warship_delta: int,
    freighter_delta: int,
) -> None:
    if expected_count <= 0:
        return
    existing = _placeholder_rows_for_turn(ledger, turn_number, ship_class=ship_class)
    for _ in range(expected_count - len(existing)):
        record = FleetShipRecord(
            record_id=str(uuid.uuid4()),
            fields=FleetShipRecordFields(
                built_turn=FleetFieldKnown(turn_number),
            ),
        )
        append_fleet_evidence_event(
            record,
            _scoreboard_delta_event(
                turn=turn_number,
                ship_class=ship_class,
                warship_delta=warship_delta,
                freighter_delta=freighter_delta,
            ),
        )
        ledger.records.append(record)


def _placeholder_rows_for_turn(
    ledger: FleetAcquisitionLedger,
    turn_number: int,
    *,
    ship_class: FleetShipClass,
) -> list[FleetShipRecord]:
    rows: list[FleetShipRecord] = []
    for record in ledger.records:
        if record.disposition != "active":
            continue
        event = _scoreboard_acquisition_event(record, turn_number)
        if event is None:
            continue
        if event.payload.get("shipClass") == ship_class:
            rows.append(record)
    return rows


def _scoreboard_acquisition_event(
    record: FleetShipRecord,
    turn_number: int,
) -> FleetEvidenceEvent | None:
    for event in record.events:
        if event.kind != "scoreboard_delta" or event.turn != turn_number:
            continue
        warship_delta = event.payload.get("warshipDelta", 0)
        freighter_delta = event.payload.get("freighterDelta", 0)
        if not isinstance(warship_delta, int) or isinstance(warship_delta, bool):
            continue
        if not isinstance(freighter_delta, int) or isinstance(freighter_delta, bool):
            continue
        if warship_delta > 0 or freighter_delta > 0:
            return event
    return None


def _scoreboard_delta_event(
    *,
    turn: int,
    ship_class: FleetShipClass,
    warship_delta: int,
    freighter_delta: int,
) -> FleetEvidenceEvent:
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind="scoreboard_delta",
        turn=turn,
        source=SCOREBOARD_SOURCE,
        payload={
            "shipClass": ship_class,
            "warshipDelta": warship_delta,
            "freighterDelta": freighter_delta,
        },
    )
