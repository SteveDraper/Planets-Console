"""Process-wide scheduler adapter for fleet table stream orchestrator submissions."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.fleet_table_player_run import (
    FleetLedgerWireProgressTracker,
    FleetPlayerStreamSession,
    _initial_wire_before_ledger,
    wire_materialized_complete_event,
    wire_materialized_player_events,
)
from api.analytics.fleet.fleet_table_stream_registry import wake_fleet_table_stream_multiplex
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.analytics.fleet.types import PersistedFleetLedger
from api.analytics.options import TurnAnalyticsOptions
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator, ComputeRequest
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.models.game import TurnInfo
from api.streaming.table_stream.scope_guard import TableStreamScopeGuard
from api.transport.fleet_table_stream import fleet_error_event

__all__ = [
    "FleetTableStreamScheduler",
    "get_fleet_table_stream_scheduler",
    "reset_fleet_table_stream_scheduler_for_tests",
]


@dataclass
class _FleetStreamOrchestratorBinding:
    """One table-stream's leader context on the process-wide singleton orchestrator."""

    orchestrator: ComputeOrchestrator
    unregister_listener: Callable[[], None]
    query_context: AnalyticQueryContext


@dataclass
class _FleetPlayerOrchestratorRun:
    session: FleetPlayerStreamSession
    host_turn_number: int
    progress_tracker: FleetLedgerWireProgressTracker
    root_scope: ComputeScope


class FleetTableStreamScheduler:
    """Table-stream adapter: one orchestrator submission per player (fair submit).

    Fairness is about **submit** grain (one DAG root per player), not wire
    serialization. The connect path multiplexes all admitted player queues so
    progress events from any player reach the SPA as compute completes.
    """

    def __init__(self) -> None:
        self._runs: dict[str, _FleetPlayerOrchestratorRun] = {}
        self._lock = threading.Lock()
        self._scope_guard = TableStreamScopeGuard[FleetTableStreamScope]()
        self._stream_bindings: dict[str, _FleetStreamOrchestratorBinding] = {}

    def begin_scope(self, scope: FleetTableStreamScope) -> str:
        with self._lock:
            return self._scope_guard.begin_scope_locked(
                scope,
                on_same_scope_preempt=self._preempt_active_table_stream_locked,
                on_scope_change=self._invalidate_retained_state_locked,
            )

    def owns_table_stream(self, stream_token: str) -> bool:
        with self._lock:
            return self._scope_guard.owns_table_stream_locked(stream_token)

    def active_scope_matches(self, scope: FleetTableStreamScope) -> bool:
        with self._lock:
            return self._scope_guard.active_scope_matches_locked(scope)

    def row_run_for_player(
        self,
        scope: FleetTableStreamScope,
        player_id: int,
    ) -> FleetPlayerStreamSession | None:
        with self._lock:
            for run in self._runs.values():
                session = run.session
                if (
                    session.game_id == scope.game_id
                    and session.perspective == scope.perspective
                    and session.turn.settings.turn == scope.turn_number
                    and session.player_id == player_id
                ):
                    return session
            return None

    def enqueue_player_run(
        self,
        session: FleetPlayerStreamSession,
        *,
        fleet_services: FleetComputeServices,
        persistence: FleetSnapshotPersistenceService,
        stream_token: str | None = None,
    ) -> FleetPlayerStreamSession | None:
        submit_binding: _FleetStreamOrchestratorBinding | None = None
        submit_scope: ComputeScope | None = None
        with self._lock:
            if (
                stream_token is not None
                and self._scope_guard.active_table_stream_token != stream_token
            ):
                return None
            for existing in self._runs.values():
                if existing.session.player_id == session.player_id:
                    return existing.session

            if stream_token is None:
                return None

            binding = self._binding_for_stream_locked(
                stream_token,
                host_turn=session.turn,
                fleet_services=fleet_services,
            )
            host_turn_number = session.turn.settings.turn
            player_id = session.player_id
            before_persisted = persistence.get_ledger(
                fleet_services.game_id,
                fleet_services.perspective,
                host_turn_number,
                player_id,
            )
            progress_tracker = FleetLedgerWireProgressTracker(
                host_turn=session.turn,
                wire_before=_initial_wire_before_ledger(
                    persistence=persistence,
                    game_id=fleet_services.game_id,
                    perspective=fleet_services.perspective,
                    player_id=player_id,
                    host_turn=session.turn,
                    before_persisted=before_persisted,
                ),
            )
            root_scope = ComputeScope(
                analytic_id=ANALYTIC_ID,
                game_id=fleet_services.game_id,
                perspective=fleet_services.perspective,
                turn=host_turn_number,
                player_id=player_id,
            )
            run = _FleetPlayerOrchestratorRun(
                session=session,
                host_turn_number=host_turn_number,
                progress_tracker=progress_tracker,
                root_scope=root_scope,
            )
            self._runs[session.run_id] = run
            # Submit outside the scheduler lock: ``orchestrator.submit`` drains diagnostics
            # listeners and may re-enter scores persist / fleet reschedule paths that need
            # this lock (ABBA with pool workers finishing ``tier_solve`` persist).
            # force_fresh: scores evidence invalidation reschedules while a prior fleet@N
            # node may still be ``complete`` on this orchestrator. Without force_fresh,
            # submit attaches to that terminal node and never rematerializes refined ledgers.
            submit_binding = binding
            submit_scope = root_scope

        if submit_binding is not None and submit_scope is not None:
            submit_binding.orchestrator.submit(
                ComputeRequest(
                    scope=submit_scope,
                    priority_band="stream_attached",
                    force_fresh=True,
                    ctx=submit_binding.query_context,
                )
            )
        return session

    def cancel_player_run(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run.session.cancel_token.cancel()
            self._runs.pop(run_id, None)

    def end_fleet_table_stream(
        self,
        scope: FleetTableStreamScope,
        sessions: tuple[FleetPlayerStreamSession, ...],
        *,
        stream_token: str,
    ) -> None:
        with self._lock:
            self._scope_guard.end_table_stream_locked(scope, stream_token)
            for session in sessions:
                session.cancel_token.cancel()
                self._runs.pop(session.run_id, None)
            binding = self._stream_bindings.pop(stream_token, None)
            if binding is not None:
                self._release_stream_binding_locked(binding)

    def _binding_for_stream_locked(
        self,
        stream_token: str,
        *,
        host_turn: TurnInfo,
        fleet_services: FleetComputeServices,
    ) -> _FleetStreamOrchestratorBinding:
        existing = self._stream_bindings.get(stream_token)
        if existing is not None:
            return existing
        query_ctx = _query_context_for_services(fleet_services, host_turn=host_turn)
        orchestrator = get_compute_orchestrator()
        unregister = orchestrator.register_node_complete_listener(
            lambda scope, node: self._on_orchestrator_node_complete(scope, node)
        )
        binding = _FleetStreamOrchestratorBinding(
            orchestrator=orchestrator,
            unregister_listener=unregister,
            query_context=query_ctx,
        )
        self._stream_bindings[stream_token] = binding
        return binding

    def _on_orchestrator_node_complete(
        self,
        scope: ComputeScope,
        node: ComputeNodeRun,
    ) -> None:
        if scope.analytic_id != ANALYTIC_ID:
            return
        if scope.turn == "*" or not isinstance(scope.turn, int):
            return
        if scope.player_id == "*" or not isinstance(scope.player_id, int):
            return

        with self._lock:
            matching_runs = [
                run
                for run in self._runs.values()
                if run.session.player_id == scope.player_id
                and run.session.game_id == scope.game_id
                and run.session.perspective == scope.perspective
                and scope.turn <= run.host_turn_number
            ]

        for run in matching_runs:
            session = run.session
            cancelled = session.cancel_token.is_cancelled()
            if node.state == "failed":
                from api.compute.errors import ComputeScopeAbortedError

                # Scores row cancel aborts the singleton scores node; that must not
                # surface as a fleet table error while dependents wait for reschedule.
                if isinstance(node.error, ComputeScopeAbortedError):
                    continue
                if node.error is not None and "scores inference row run cancelled" in str(
                    node.error
                ):
                    continue
                detail = (
                    str(node.error)
                    if node.error is not None
                    else "Fleet ledger materialization failed"
                )
                _emit_fleet_materialization_error(session, cancelled=cancelled, detail=detail)
                continue
            if node.state != "complete" or node.result_wire is None:
                continue
            persisted = _persisted_ledger_from_node_or_storage(
                scope,
                node,
                stream_bindings=self._stream_bindings,
            )
            if persisted is None:
                _emit_fleet_materialization_error(
                    session,
                    cancelled=cancelled,
                    detail="Fleet ledger materialization failed",
                )
                continue
            stream_events = _node_complete_stream_events(
                scope_turn=scope.turn,
                host_turn_number=run.host_turn_number,
                tracker=run.progress_tracker,
                persisted=persisted,
                session_turn=session.turn,
                cancelled=cancelled,
            )
            for event in stream_events:
                session.event_queue.put(event)
            if stream_events:
                _wake_multiplex_for_session(session)

    def _release_stream_binding_locked(
        self,
        binding: _FleetStreamOrchestratorBinding,
    ) -> None:
        binding.unregister_listener()

    def _preempt_active_table_stream_locked(self) -> None:
        for run in self._runs.values():
            run.session.cancel_token.cancel()
        self._runs.clear()
        for stream_token in list(self._stream_bindings):
            binding = self._stream_bindings.pop(stream_token)
            self._release_stream_binding_locked(binding)

    def _invalidate_retained_state_locked(self) -> None:
        self._preempt_active_table_stream_locked()


def _emit_fleet_materialization_error(
    session: FleetPlayerStreamSession,
    *,
    cancelled: bool,
    detail: str,
) -> None:
    if not cancelled:
        session.event_queue.put(fleet_error_event(detail))
        _wake_multiplex_for_session(session)


def _persisted_ledger_from_node_or_storage(
    scope: ComputeScope,
    node: ComputeNodeRun,
    *,
    stream_bindings: dict[str, _FleetStreamOrchestratorBinding],
) -> PersistedFleetLedger | None:
    """Resolve a final ledger from the node wire or durable persistence.

    Satisfaction short-circuit may complete with ``{}``; reload from storage so
    the stream still emits progress instead of a false materialization error.
    """
    if isinstance(node.result_wire, dict):
        persisted_wire = node.result_wire.get("persistedLedgerWire")
        if isinstance(persisted_wire, dict):
            return persisted_fleet_ledger_from_json(persisted_wire)
    if scope.player_id == "*" or not isinstance(scope.player_id, int):
        return None
    if scope.turn == "*" or not isinstance(scope.turn, int):
        return None
    from api.analytics.fleet.compute_services import resolve_fleet_services

    for binding in stream_bindings.values():
        services = resolve_fleet_services(binding.query_context)
        persisted = services.persistence.get_ledger(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
        )
        if persisted is not None and persisted.provenance.is_final:
            return persisted
    return None


def _wake_multiplex_for_session(session: FleetPlayerStreamSession) -> None:
    wake_fleet_table_stream_multiplex(
        FleetTableStreamScope(
            game_id=session.game_id,
            perspective=session.perspective,
            turn_number=session.turn.settings.turn,
        )
    )


def _node_complete_stream_events(
    *,
    scope_turn: int,
    host_turn_number: int,
    tracker: FleetLedgerWireProgressTracker,
    persisted: PersistedFleetLedger,
    session_turn: TurnInfo,
    cancelled: bool,
) -> tuple[dict[str, object], ...]:
    if scope_turn < host_turn_number:
        if cancelled:
            return ()
        return tracker.leg_progress_events(persisted)

    if scope_turn != host_turn_number:
        return ()

    if tracker.emitted_progress:
        return (
            *tracker.leg_progress_events(persisted),
            wire_materialized_complete_event(persisted),
        )

    if cancelled:
        return ()

    return wire_materialized_player_events(
        before=tracker.wire_before,
        persisted=persisted,
        host_turn=session_turn,
    )


def _query_context_for_services(
    fleet_services: FleetComputeServices,
    *,
    host_turn: TurnInfo,
):
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID

    export_services: dict[str, object] = {ANALYTIC_ID: fleet_services}
    if fleet_services.inference_materialization is not None:
        scores_services = fleet_services.inference_materialization.inference.scores_services
    else:
        scores_services = ScoresExportContext()
    export_services[SCORES_ANALYTIC_ID] = scores_services
    return make_analytic_query_context(
        host_turn,
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services=export_services,
    )


_process_scheduler: FleetTableStreamScheduler | None = None
_process_scheduler_lock = threading.Lock()


def get_fleet_table_stream_scheduler() -> FleetTableStreamScheduler:
    global _process_scheduler
    with _process_scheduler_lock:
        if _process_scheduler is None:
            _process_scheduler = FleetTableStreamScheduler()
        return _process_scheduler


def reset_fleet_table_stream_scheduler_for_tests() -> None:
    global _process_scheduler
    from api.compute.runtime import reset_orchestrators_for_tests

    with _process_scheduler_lock:
        _process_scheduler = FleetTableStreamScheduler()
    reset_orchestrators_for_tests()
