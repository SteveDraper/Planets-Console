"""Per-player fleet table stream session and wire event helpers."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from dataclasses import dataclass, field

from api.analytics.fleet.chain import (
    _find_chain_anchor_for_player,
    advance_ledger_to_turn,
)
from api.analytics.fleet.serialization import (
    fleet_ship_record_to_json,
)
from api.analytics.fleet.table_wire import (
    fleet_acquisition_ledger_to_table_wire,
    fleet_ship_record_to_table_wire,
)
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipRecord, PersistedFleetLedger
from api.models.game import TurnInfo
from api.transport.fleet_table_stream import (
    fleet_complete_event,
    fleet_ledger_updated_event,
    fleet_provenance_event,
    fleet_record_refined_event,
)


class FleetPlayerCancelToken:
    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


@dataclass
class FleetPlayerStreamSession:
    player_id: int
    turn: TurnInfo
    game_id: int
    perspective: int
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cancel_token: FleetPlayerCancelToken = field(default_factory=FleetPlayerCancelToken)
    event_queue: queue.Queue[dict[str, object]] = field(default_factory=queue.Queue)


@dataclass
class ScheduledFleetPlayer:
    player_id: int
    session: FleetPlayerStreamSession


def _records_by_id(ledger: FleetAcquisitionLedger | None) -> dict[str, FleetShipRecord]:
    if ledger is None:
        return {}
    return {record.record_id: record for record in ledger.records}


def _record_refined(before: FleetShipRecord, after: FleetShipRecord) -> bool:
    before_wire = fleet_ship_record_to_json(before)
    after_wire = fleet_ship_record_to_json(after)
    return json.dumps(before_wire, sort_keys=True) != json.dumps(after_wire, sort_keys=True)


def _wire_provenance(persisted: PersistedFleetLedger) -> dict[str, object]:
    return fleet_provenance_event(
        turn_evidence_at_n=persisted.provenance.turn_evidence_at_n,
        prior_ledger_at_n_minus_1=persisted.provenance.prior_ledger_at_n_minus_1,
        is_final=persisted.provenance.is_final,
    )


def _host_turn_shaped_ledger(
    persisted: PersistedFleetLedger,
    host_turn: TurnInfo,
) -> FleetAcquisitionLedger:
    """Shape interim gap-fill ledger for the host-turn fleet table tile."""
    return advance_ledger_to_turn(persisted.ledger, host_turn)


def _initial_wire_before_ledger(
    *,
    persistence,
    game_id: int,
    perspective: int,
    player_id: int,
    host_turn: TurnInfo,
    before_persisted: PersistedFleetLedger | None,
) -> FleetAcquisitionLedger | None:
    if before_persisted is not None:
        return _host_turn_shaped_ledger(before_persisted, host_turn)
    _anchor_turn, anchor_persisted = _find_chain_anchor_for_player(
        persistence,
        game_id,
        perspective,
        player_id,
        host_turn.settings.turn,
    )
    if anchor_persisted is None:
        return None
    return _host_turn_shaped_ledger(anchor_persisted, host_turn)


def wire_ledger_progress_events(
    *,
    before: FleetAcquisitionLedger | None,
    persisted: PersistedFleetLedger,
    host_turn: TurnInfo,
) -> tuple[dict[str, object], ...]:
    """Build incremental stream events after one gap-fill leg toward host turn N."""
    host_shaped = _host_turn_shaped_ledger(persisted, host_turn)
    before_records = _records_by_id(before)
    after_records = _records_by_id(host_shaped)
    events: list[dict[str, object]] = []
    for record_id, record in after_records.items():
        prior = before_records.get(record_id)
        if prior is not None and _record_refined(prior, record):
            events.append(
                fleet_record_refined_event(record=fleet_ship_record_to_table_wire(record))
            )
    events.append(
        fleet_ledger_updated_event(ledger=fleet_acquisition_ledger_to_table_wire(host_shaped))
    )
    events.append(_wire_provenance(persisted))
    return tuple(events)


def wire_materialized_complete_event(
    persisted: PersistedFleetLedger,
) -> dict[str, object]:
    summary = (
        "Fleet ledger materialization complete."
        if persisted.provenance.is_final
        else "Fleet ledger materialized with open provenance legs."
    )
    return fleet_complete_event(
        is_final=persisted.provenance.is_final,
        summary=summary,
    )


def wire_cached_player_events(persisted: PersistedFleetLedger) -> tuple[dict[str, object], ...]:
    """Replay terminal stream events for an ensure-final cached ledger."""
    return (
        fleet_ledger_updated_event(ledger=fleet_acquisition_ledger_to_table_wire(persisted.ledger)),
        _wire_provenance(persisted),
        fleet_complete_event(
            is_final=True,
            summary="Fleet ledger loaded from cache.",
        ),
    )


def wire_materialized_player_events(
    *,
    before: FleetAcquisitionLedger | None,
    persisted: PersistedFleetLedger,
    host_turn: TurnInfo,
) -> tuple[dict[str, object], ...]:
    """Build terminal wire events after materialization completes for one player."""
    return (
        *wire_ledger_progress_events(
            before=before,
            persisted=persisted,
            host_turn=host_turn,
        ),
        wire_materialized_complete_event(persisted),
    )


@dataclass
class FleetLedgerWireProgressTracker:
    """Own host-turn wire-before state for incremental gap-fill stream events."""

    host_turn: TurnInfo
    wire_before: FleetAcquisitionLedger | None = None
    emitted_progress: bool = False

    def leg_progress_events(
        self,
        persisted: PersistedFleetLedger,
    ) -> tuple[dict[str, object], ...]:
        events = wire_ledger_progress_events(
            before=self.wire_before,
            persisted=persisted,
            host_turn=self.host_turn,
        )
        self.wire_before = _host_turn_shaped_ledger(persisted, self.host_turn)
        self.emitted_progress = True
        return events
