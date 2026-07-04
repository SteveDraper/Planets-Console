"""Per-player fleet table stream session and background materialization job."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from dataclasses import dataclass, field

from api.analytics.fleet.chain import (
    _find_chain_anchor_for_player,
    advance_ledger_to_turn,
    get_or_materialize_fleet_ledger_for_player,
)
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.serialization import (
    fleet_ship_record_to_json,
)
from api.analytics.fleet.table_wire import (
    fleet_acquisition_ledger_to_table_wire,
    fleet_ship_record_to_table_wire,
)
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipRecord, PersistedFleetLedger
from api.analytics.turn_roster import iter_turn_players
from api.errors import PlanetsConsoleError
from api.models.game import TurnInfo
from api.transport.fleet_table_stream import (
    fleet_complete_event,
    fleet_error_event,
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


def run_fleet_player_materialization_job(
    session: FleetPlayerStreamSession,
    *,
    fleet_services: FleetComputeServices,
    persistence,
) -> None:
    """Materialize one player's fleet ledger and enqueue stream wire events."""
    if session.cancel_token.is_cancelled():
        return

    player_id = session.player_id
    turn = session.turn
    roster_ids = {player.id for player in iter_turn_players(turn)}
    if player_id not in roster_ids:
        session.event_queue.put(
            fleet_error_event(f"Player {player_id} is not on turn {turn.settings.turn} roster")
        )
        return

    turn_number = turn.settings.turn
    before_persisted = persistence.get_ledger(
        fleet_services.game_id,
        fleet_services.perspective,
        turn_number,
        player_id,
    )
    progress_tracker = FleetLedgerWireProgressTracker(
        host_turn=turn,
        wire_before=_initial_wire_before_ledger(
            persistence=persistence,
            game_id=fleet_services.game_id,
            perspective=fleet_services.perspective,
            player_id=player_id,
            host_turn=turn,
            before_persisted=before_persisted,
        ),
    )

    def on_progress(
        persisted_leg: PersistedFleetLedger,
        _materialize_turn: int,
    ) -> None:
        if session.cancel_token.is_cancelled():
            return
        for event in progress_tracker.leg_progress_events(persisted_leg):
            session.event_queue.put(event)

    try:
        persisted = get_or_materialize_fleet_ledger_for_player(
            persistence,
            fleet_services.game_id,
            fleet_services.perspective,
            player_id,
            turn,
            load_turn=fleet_services.load_turn,
            inference_materialization=fleet_services.inference_materialization,
            on_progress=on_progress,
        )
    except PlanetsConsoleError as exc:
        detail = str(exc) or "Fleet ledger materialization failed"
        session.event_queue.put(fleet_error_event(detail))
        return
    except Exception:
        session.event_queue.put(fleet_error_event("Fleet ledger materialization failed"))
        return

    if session.cancel_token.is_cancelled():
        return

    if progress_tracker.emitted_progress:
        session.event_queue.put(wire_materialized_complete_event(persisted))
        return

    for event in wire_materialized_player_events(
        before=progress_tracker.wire_before,
        persisted=persisted,
        host_turn=turn,
    ):
        session.event_queue.put(event)
