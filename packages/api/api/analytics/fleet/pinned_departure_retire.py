"""Retire exact-set pinned departures from scores persist onto fleet@T.

Spec-only pins omit record ids and do not change disposition. Placeholder
departures are not ingested here -- they are skipped by fleet explode.
Contract: design-military-score-build-inference.md §3.12.
"""

from __future__ import annotations

import uuid

from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetEvidenceEvent,
    FleetShipClass,
    FleetShipRecord,
)
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    ExactSetDeparturePin,
    ExactSetPinRecord,
)

SCORES_INFERENCE_SOURCE = "scores.inference"


def retire_exact_set_pinned_departures(
    ledger: FleetAcquisitionLedger,
    *,
    turn_number: int,
    pins: tuple[ExactSetDeparturePin, ...],
) -> None:
    """Set named exact-set pin records to lost or traded. Mutates ledger.

    Missing or already non-active records are left unchanged. Spec-only persist
    supplies an empty pin list and is a no-op.
    """
    records_by_id = {record.record_id: record for record in ledger.records}
    for pin in pins:
        for entry in pin.records:
            record = records_by_id.get(entry.record_id)
            if record is None or record.disposition != "active":
                continue
            _retire_named_record(
                record,
                entry,
                ship_class=pin.ship_class,
                turn_number=turn_number,
            )


def _retire_named_record(
    record: FleetShipRecord,
    entry: ExactSetPinRecord,
    *,
    ship_class: FleetShipClass,
    turn_number: int,
) -> None:
    record.disposition = entry.disposition
    payload: dict[str, object] = {
        "disposition": entry.disposition,
        "shipClass": ship_class,
    }
    if entry.counterparty_player_id is not None:
        payload["counterpartyPlayerId"] = entry.counterparty_player_id
    append_fleet_evidence_event(
        record,
        FleetEvidenceEvent(
            event_id=str(uuid.uuid4()),
            kind="disposition_change",
            turn=turn_number,
            source=SCORES_INFERENCE_SOURCE,
            payload=payload,
        ),
    )
