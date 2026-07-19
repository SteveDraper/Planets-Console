"""Process-wide orchestrator adapter for scores inference table stream tier work."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
from api.analytics.military_score_inference.inference_row_runner import InferenceTierJobCallbacks
from api.analytics.military_score_inference.inference_stream_domain_events import (
    GlobalPauseChanged,
    HeldSolutionsUpdated,
    RowComplete,
    TierProgress,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_resolution import (
    InferenceStreamResolutionMixin,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_scope_outcomes import (
    InferenceStreamScopeOutcomesMixin,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_stream_teardown import (
    HeldTierSubmission,
    InferenceStreamOrchestratorBinding,
    InferenceStreamTeardownMixin,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    wake_inference_table_stream_multiplex,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.scope import ComputeScope
from api.errors import ValidationError
from api.streaming.table_stream.scope_guard import TableStreamScopeGuard

__all__ = [
    "InferenceRowScheduler",
    "create_inference_row_scheduler",
    "get_inference_row_scheduler",
    "reset_inference_row_scheduler_for_tests",
]

OnHeldSolutionsUpdatedCallback = Callable[[InferenceRowStreamSession], None]


class InferenceRowScheduler(
    InferenceStreamTeardownMixin,
    InferenceStreamScopeOutcomesMixin,
    InferenceStreamResolutionMixin,
):
    """Fair orchestrator adapter: one tier_solve submission per scoreboard row."""

    def __init__(
        self,
        *,
        on_held_solutions_updated: OnHeldSolutionsUpdatedCallback | None = None,
        defer_orchestrator_submit: bool = False,
        worker_count: int | None = None,
        **_deprecated_kwargs: object,
    ) -> None:
        del _deprecated_kwargs
        self._on_held_solutions_updated = on_held_solutions_updated
        if worker_count == 0:
            defer_orchestrator_submit = True
        self._defer_orchestrator_submit = defer_orchestrator_submit
        self._runs: dict[str, ComputeScope] = {}
        # Live RowRun objects owned by this scheduler. Tier registry may be cleared
        # on detach while a background adopt still needs the RowRun handle.
        self._row_runs_by_id: dict[str, RowRun] = {}
        # Execution identity for cancel abort, captured after submit/wake *outside*
        # the scheduler lock. ``cancel_run`` must never call into the orchestrator
        # while holding ``_lock`` (scheduler → orch nests ABBA with orch drain →
        # scheduler listeners, which also hangs diagnostics snapshot on orch).
        self._execution_generation_by_run_id: dict[str, int] = {}
        # RLock: adapter methods hold this lock across orchestrator calls. When resume_globally
        # calls _dispatch_ready_orchestrator_work_locked, dispatch_ready_work drains post-lock
        # callbacks in the caller thread and the scope-outcome listener
        # (_on_orchestrator_scope_outcome, _finalize_row_run) can re-acquire the lock on that
        # thread. pause_globally shares the same lock while updating dispatch gates. Production
        # tier_solve uses the thread pool backend, so listener completion is usually async rather
        # than synchronous in the dispatch caller.
        self._lock = threading.RLock()
        self._scope_guard = TableStreamScopeGuard[InferenceStreamScope]()
        self._stream_bindings: dict[str, InferenceStreamOrchestratorBinding] = {}
        self._globally_paused = False
        self._held_initial_submissions: list[HeldTierSubmission] = []
        from api.compute.runtime import get_compute_orchestrator

        # All production score bindings share the process orchestrator. Its outcome
        # observer delivers immutable parked and terminal snapshots exactly once.
        orch = get_compute_orchestrator()
        self._unregister_scope_outcome = orch.observers.register_scope_outcome_listener(
            self._on_orchestrator_scope_outcome,
        )

    def owns_table_stream(self, stream_token: str) -> bool:
        with self._lock:
            return self._scope_guard.owns_table_stream_locked(stream_token)

    def active_scope_matches(self, scope: InferenceStreamScope) -> bool:
        with self._lock:
            return self._scope_guard.active_scope_matches_locked(scope)

    def should_reschedule_scores_row_after_fleet_persist(
        self,
        scope: InferenceStreamScope,
        event: FleetLedgerPersistedEvent,
        *,
        invalidate_row: Callable[[], None],
    ) -> bool:
        """Return whether scores@N should reschedule after one fleet ledger persist.

        Runs invalidation and the skip decision under the scheduler lock.
        """
        with self._lock:
            invalidate_row()
            return not self._should_skip_reschedule_for_fleet_persist_locked(scope, event)

    def _stream_binding_for_scope_locked(
        self,
        scope: InferenceStreamScope,
    ) -> InferenceStreamOrchestratorBinding | None:
        if not self._scope_guard.active_scope_matches_locked(scope):
            return None
        stream_token = self._scope_guard.active_table_stream_token
        if stream_token is None:
            return None
        return self._stream_bindings.get(stream_token)

    def _should_skip_reschedule_for_fleet_persist_locked(
        self,
        scope: InferenceStreamScope,
        event: FleetLedgerPersistedEvent,
    ) -> bool:
        """Return whether to skip in-place reschedule for this fleet persist notification.

        Own-DAG fleet persist notifications fire only after the fleet node is
        ``complete`` (deferred until after ``_complete_node``). Skip when scores is
        ``waiting_deps`` on that fleet scope and the completed fleet node's
        materialization version matches the notification. A persist while fleet is
        still non-terminal is treated as external and must reschedule.
        """
        binding = self._stream_binding_for_scope_locked(scope)
        if binding is None:
            return False

        scores_scope = ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn=scope.turn_number,
            player_id=event.player_id,
        )
        fleet_scope = self._fleet_scope_for_event(scope, event)
        orchestrator = binding.orchestrator
        scores_node = orchestrator.nodes.get(scores_scope)
        if scores_node is None or scores_node.state != "waiting_deps":
            return False
        if fleet_scope not in scores_node.dependency_scopes:
            return False

        fleet_node = orchestrator.nodes.get(fleet_scope)
        if fleet_node is None or fleet_node.state != "complete":
            return False

        return not self._fleet_versions_conflict(fleet_node, event)

    @staticmethod
    def _fleet_scope_for_event(
        scope: InferenceStreamScope,
        event: FleetLedgerPersistedEvent,
    ) -> ComputeScope:
        from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID

        return ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn=event.fleet_turn,
            player_id=event.player_id,
        )

    @staticmethod
    def _fleet_versions_conflict(
        fleet_node: object,
        event: FleetLedgerPersistedEvent,
    ) -> bool:
        from api.analytics.fleet.serialization import (
            materialization_version_from_fleet_compute_result_wire,
        )

        result_wire = getattr(fleet_node, "result_wire", None)
        stream_version = materialization_version_from_fleet_compute_result_wire(result_wire)
        if stream_version is None:
            return False
        return stream_version != event.materialization_version

    def row_run_for_player(
        self,
        scope: InferenceStreamScope,
        player_id: int,
    ) -> RowRun | None:
        with self._lock:
            for run_id, root_scope in self._runs.items():
                if (
                    root_scope.game_id == scope.game_id
                    and root_scope.perspective == scope.perspective
                    and root_scope.turn == scope.turn_number
                    and root_scope.player_id == player_id
                ):
                    owned = self._row_runs_by_id.get(run_id)
                    if owned is not None:
                        return owned
                    return self._adapter_row_run(run_id)
            return None

    def _global_pause_status_locked(self, scope: InferenceStreamScope) -> dict[str, object]:
        active_scope = self._scope_guard.active_scope
        scope_matches = active_scope == scope
        held_jobs, held_continuations = self._held_work_counts_locked()
        return {
            "gameId": scope.game_id,
            "perspective": scope.perspective,
            "turn": scope.turn_number,
            "paused": self._globally_paused and scope_matches,
            "activeScope": (
                {
                    "gameId": active_scope.game_id,
                    "perspective": active_scope.perspective,
                    "turn": active_scope.turn_number,
                }
                if active_scope is not None
                else None
            ),
            "heldJobCount": held_jobs if scope_matches else 0,
            "heldContinuationCount": held_continuations if scope_matches else 0,
            "activeSessionCount": len(self._runs) if scope_matches else 0,
        }

    def global_pause_status(self, scope: InferenceStreamScope) -> dict[str, object]:
        with self._lock:
            return self._global_pause_status_locked(scope)

    def _require_active_stream_for_scope_locked(self, scope: InferenceStreamScope) -> None:
        if not self._scope_guard.has_active_table_stream or self._scope_guard.active_scope != scope:
            raise ValidationError(
                "Global pause requires an active inference table stream for this scope."
            )

    def pause_globally(self, scope: InferenceStreamScope) -> dict[str, object]:
        """Soft pause: hold tier_solve dispatch; in-flight tier work is not cancelled."""
        with self._lock:
            self._require_active_stream_for_scope_locked(scope)
            if self._globally_paused:
                return self._global_pause_status_locked(scope)
            self._globally_paused = True
            bindings = tuple(self._stream_bindings.values())
            self._broadcast_global_pause_locked(paused=True)
            status = self._global_pause_status_locked(scope)
        # Never register orchestrator gates while holding the scheduler lock:
        # job-wire builders / ensure paths take this lock under dispatch.
        self._sync_pause_dispatch_gates(bindings, paused=True)
        return status

    def resume_globally(self, scope: InferenceStreamScope) -> dict[str, object]:
        with self._lock:
            self._require_active_stream_for_scope_locked(scope)
            if not self._globally_paused:
                return self._global_pause_status_locked(scope)
            self._globally_paused = False
            bindings = tuple(self._stream_bindings.values())
            held = tuple(self._held_initial_submissions)
            self._held_initial_submissions.clear()
            self._broadcast_global_pause_locked(paused=False)
            status = self._global_pause_status_locked(scope)
        # Submit held work outside the scheduler lock (same ABBA risk as enqueue).
        for held_item in held:
            binding = self._stream_bindings.get(held_item.stream_token)
            if binding is not None:
                self._submit_tier_solve_locked(binding, held_item.root_scope)
        self._sync_pause_dispatch_gates(bindings, paused=False)
        for binding in bindings:
            binding.orchestrator.dispatch_ready_work()
        return status

    def unregister_session(self, run_id: str) -> None:
        with self._lock:
            self._remove_run_locked(run_id)

    def detach_inference_stream(
        self,
        scope: InferenceStreamScope,
        sessions: tuple[InferenceRowStreamSession, ...],
        *,
        stream_token: str,
    ) -> None:
        """Detach a table stream without cancelling its in-flight row runs."""
        remaining_bindings: tuple[InferenceStreamOrchestratorBinding, ...] = ()
        clear_pause_gates = False
        with self._lock:
            owns_scope = self._scope_guard.end_table_stream_locked(scope, stream_token)
            for session in sessions:
                self._remove_run_locked(session.run_id)
            self._drop_held_for_stream_locked(stream_token)
            binding = self._stream_bindings.pop(stream_token, None)
            if binding is not None:
                self._release_stream_binding_locked(binding)
            if owns_scope:
                clear_pause_gates = self._clear_global_pause_for_active_scope_locked(scope)
                remaining_bindings = tuple(self._stream_bindings.values())
        if clear_pause_gates:
            self._sync_pause_dispatch_gates(remaining_bindings, paused=False)

    def _clear_global_pause_for_active_scope_locked(
        self,
        scope: InferenceStreamScope,
    ) -> bool:
        """Clear pause flag under lock. Return whether callers must sync gates outside."""
        if self._scope_guard.active_scope != scope:
            return False
        self._globally_paused = False
        self._held_initial_submissions.clear()
        return True

    def enqueue_tier_ladder(
        self,
        session: InferenceRowStreamSession,
        *,
        orchestration: InferenceStreamOrchestration | None = None,
        stream_token: str | None = None,
    ) -> None:
        submit_binding: InferenceStreamOrchestratorBinding | None = None
        submit_scope: ComputeScope | None = None
        wake_parked_scope: ComputeScope | None = None
        with self._lock:
            resolved_token = (
                stream_token
                if stream_token is not None
                else self._scope_guard.active_table_stream_token
            )

            row_run = RowRun(session)
            from api.analytics.scores.tier_row_run_registry import register_row_run

            register_row_run(row_run, orchestration=orchestration)
            self._register_tier_callbacks_for_run(row_run)
            root_scope = self._root_scope_for_session(session)
            self._runs[session.run_id] = root_scope
            self._row_runs_by_id[session.run_id] = row_run
            if self._defer_orchestrator_submit:
                return
            if resolved_token is None:
                # Background ensure / adopt registered a RowRun with no stream submit.
                # Soft-parked scores nodes must still get an explicit force_fresh wake.
                wake_parked_scope = root_scope
            elif self._scope_guard.active_table_stream_token != resolved_token:
                return
            else:
                # Create the stream binding even when paused so resume can submit held
                # work (``resume_globally`` looks up binding by stream_token).
                binding = self._binding_for_stream_locked(resolved_token, session=session)
                if self._globally_paused:
                    self._held_initial_submissions.append(
                        HeldTierSubmission(stream_token=resolved_token, root_scope=root_scope)
                    )
                    return
                # Submit outside the scheduler lock: ``orchestrator.submit`` drains diagnostics
                # listeners that must not nest scheduler <-> orchestrator locks.
                submit_binding = binding
                submit_scope = root_scope
        if submit_binding is not None and submit_scope is not None:
            self._submit_tier_solve_locked(submit_binding, submit_scope)
        elif wake_parked_scope is not None:
            self._wake_parked_scores_after_row_run_adopt(wake_parked_scope, session)

    def cancel_row_run(self, run_id: str) -> None:
        """Cancel one row run."""
        self.cancel_run(run_id)

    def clear_global_pause_for_scope(self, scope: InferenceStreamScope) -> None:
        bindings: tuple[InferenceStreamOrchestratorBinding, ...] = ()
        cleared = False
        with self._lock:
            if self._scope_guard.active_scope == scope:
                cleared = self._clear_global_pause_for_active_scope_locked(scope)
                bindings = tuple(self._stream_bindings.values())
                self._broadcast_global_pause_locked(paused=False)
        if cleared:
            self._sync_pause_dispatch_gates(bindings, paused=False)

    def shutdown(self) -> None:
        """Reset adapter state; safe for test teardown after dropping a service stack."""
        unregister = getattr(self, "_unregister_scope_outcome", None)
        if callable(unregister):
            unregister()
            self._unregister_scope_outcome = None
        with self._lock:
            self._invalidate_retained_state_locked()

    def _emit_held_solutions(
        self,
        session: InferenceRowStreamSession,
        *,
        observation: InferenceObservation,
    ) -> None:
        row_run = self._adapter_row_run(session.run_id)
        if row_run is None:
            return
        state = row_run.ladder_state
        if state is None or state.catalog is None or not state.merged_solutions:
            return
        segment_id: str | None = None
        orchestration = row_run.orchestration
        if orchestration is not None:
            segment = orchestration.current_segment()
            if segment is not None:
                segment_id = segment.segment_id
        session.event_queue.put(
            HeldSolutionsUpdated(
                solutions=tuple(state.merged_solutions),
                catalog=state.catalog,
                observation=observation,
                segment_id=segment_id,
            )
        )
        if self._on_held_solutions_updated is not None:
            self._on_held_solutions_updated(session)
        self._wake_multiplex_for_session(session)

    def _emit_progress(self, session: InferenceRowStreamSession) -> None:
        row_run = self._adapter_row_run(session.run_id)
        if row_run is None:
            return
        state = row_run.ladder_state
        if state is None or state.catalog is None:
            return
        session.event_queue.put(
            TierProgress(
                policy_step_id=state.catalog.policy_step_id,
                combo_count=len(state.catalog.ship_build_combos),
                held_count=len(state.merged_solutions),
            )
        )
        self._wake_multiplex_for_session(session)

    def _emit_tier_started_progress(self, session: InferenceRowStreamSession) -> None:
        row_run = self._adapter_row_run(session.run_id)
        if row_run is None:
            return
        state = row_run.ladder_state
        if state is None or state.next_step_index >= len(state.policy_steps):
            return
        step = state.policy_steps[state.next_step_index]
        session.event_queue.put(
            TierProgress(
                policy_step_id=step.id,
                held_count=len(state.merged_solutions),
            )
        )
        self._wake_multiplex_for_session(session)

    def _register_tier_callbacks_for_run(self, row_run: RowRun) -> None:
        from api.analytics.scores.tier_row_run_registry import register_tier_callbacks

        session = row_run.session

        def callbacks() -> InferenceTierJobCallbacks:
            return InferenceTierJobCallbacks(
                emit_tier_started_progress=lambda: self._emit_tier_started_progress(session),
                emit_progress=lambda: self._emit_progress(session),
                emit_held_solutions=lambda observation: self._emit_held_solutions(
                    session,
                    observation=observation,
                ),
            )

        register_tier_callbacks(row_run.run_id, callbacks())

    def _binding_for_stream_locked(
        self,
        stream_token: str,
        *,
        session: InferenceRowStreamSession,
    ) -> InferenceStreamOrchestratorBinding:
        from api.compute.runtime import get_compute_orchestrator

        existing = self._stream_bindings.get(stream_token)
        if existing is not None:
            return existing
        query_ctx = _query_context_for_session(session, scheduler=self)
        binding = InferenceStreamOrchestratorBinding(
            orchestrator=get_compute_orchestrator(),
            query_context=query_ctx,
        )
        self._stream_bindings[stream_token] = binding
        self._apply_dispatch_gates_locked()
        return binding

    def _wake_parked_scores_after_row_run_adopt(
        self,
        root_scope: ComputeScope,
        session: InferenceRowStreamSession,
    ) -> None:
        """Wake a soft-parked scores node after background RowRun register."""
        from api.analytics.scores.compute_orchestration import (
            ScoresWakeReason,
            wake_scores_scope,
        )

        wake_scores_scope(
            root_scope,
            ctx=_query_context_for_session(session, scheduler=self),
            reason=ScoresWakeReason.ROW_RUN_ADOPTED,
            priority_band="background",
        )
        self._remember_execution_generation_for_scope(root_scope)

    def _broadcast_global_pause_locked(self, *, paused: bool) -> None:
        event = GlobalPauseChanged(paused=paused)
        for run_id in self._runs:
            row_run = self._adapter_row_run(run_id)
            if row_run is not None:
                row_run.session.event_queue.put(event)

    def _submit_tier_solve_locked(
        self,
        binding: InferenceStreamOrchestratorBinding,
        root_scope: ComputeScope,
    ) -> None:
        """Submit/wake tier_solve for ``root_scope``. Caller must not hold ``_lock``."""
        if self._defer_orchestrator_submit:
            return
        from api.analytics.scores.compute_orchestration import (
            ScoresWakeReason,
            wake_scores_scope,
        )

        # force_fresh may replace a prior empty/admission terminal. Reopen the multiplex
        # row so progress drains and a later RowComplete can upgrade the soft terminal.
        self._reopen_stream_row_for_force_fresh(root_scope)
        wake_scores_scope(
            root_scope,
            ctx=binding.query_context,
            reason=ScoresWakeReason.STREAM_RESCHEDULED,
            priority_band="stream_attached",
            orchestrator=binding.orchestrator,
        )
        self._remember_execution_generation_for_scope(
            root_scope,
            orchestrator=binding.orchestrator,
        )

    def _remember_execution_generation_for_scope(
        self,
        root_scope: ComputeScope,
        *,
        orchestrator: ComputeOrchestrator | None = None,
    ) -> None:
        """Cache orchestrator execution identity for later generation-scoped cancel.

        Must run without the scheduler lock held: samples the orchestrator condition.
        """
        from api.compute.runtime import get_compute_orchestrator

        orch = orchestrator if orchestrator is not None else get_compute_orchestrator()
        generation = orch.execution_generation_for_scope(root_scope)
        if generation is None:
            return
        with self._lock:
            for run_id, scope in self._runs.items():
                if scope == root_scope:
                    self._execution_generation_by_run_id[run_id] = generation

    def _drop_held_for_stream_locked(self, stream_token: str) -> None:
        self._held_initial_submissions = [
            held for held in self._held_initial_submissions if held.stream_token != stream_token
        ]

    def _held_work_counts_locked(self) -> tuple[int, int]:
        held_jobs = len(self._held_initial_submissions)
        held_continuations = 0
        if not self._globally_paused:
            return held_jobs, held_continuations
        for binding in self._stream_bindings.values():
            for root_scope in self._runs.values():
                node = binding.orchestrator.nodes.get(root_scope)
                if node is None or node.state != "ready":
                    continue
                if node.step_index == 0:
                    held_jobs += 1
                else:
                    held_continuations += 1
        return held_jobs, held_continuations

    def _apply_dispatch_gates_locked(self) -> None:
        """Apply pause gates for current bindings.

        Prefer ``_sync_pause_dispatch_gates`` outside the scheduler lock when possible.
        This in-lock path remains for stream-binding setup where the binding is new.
        """
        self._sync_pause_dispatch_gates(
            tuple(self._stream_bindings.values()),
            paused=self._globally_paused,
        )

    def _sync_pause_dispatch_gates(
        self,
        bindings: tuple[InferenceStreamOrchestratorBinding, ...],
        *,
        paused: bool,
    ) -> None:
        """Register or clear pause dispatch gates (must not hold the scheduler lock)."""
        for binding in bindings:
            if paused:
                if binding.unregister_dispatch_gate is None:
                    observers = binding.orchestrator.observers
                    binding.unregister_dispatch_gate = observers.register_dispatch_gate(
                        self._pause_dispatch_gate
                    )
            elif binding.unregister_dispatch_gate is not None:
                binding.unregister_dispatch_gate()
                binding.unregister_dispatch_gate = None

    def _dispatch_ready_orchestrator_work_locked(self) -> None:
        for binding in self._stream_bindings.values():
            binding.orchestrator.dispatch_ready_work()

    def _pause_dispatch_gate(self, node: object) -> bool:
        from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE_PROFILE_INDEX

        if not self._globally_paused:
            return True
        if node.scope.analytic_id != SCORES_ANALYTIC_ID:
            return True
        return node.profile_step_index != SCORES_TIER_SOLVE_PROFILE_INDEX

    @staticmethod
    def _root_scope_for_session(session: InferenceRowStreamSession) -> ComputeScope:
        return ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=session.game_id,
            perspective=session.perspective,
            turn=session.turn_number,
            player_id=session.player_id,
        )

    @staticmethod
    def _row_complete_from_result_wire(result_wire: object | None) -> RowComplete | None:
        if not isinstance(result_wire, dict):
            return None
        row_complete = result_wire.get("rowComplete")
        if isinstance(row_complete, RowComplete):
            return row_complete
        return None

    @staticmethod
    def _wake_multiplex_for_session(session: InferenceRowStreamSession) -> None:
        wake_inference_table_stream_multiplex(
            InferenceStreamScope(
                game_id=session.game_id,
                perspective=session.perspective,
                turn_number=session.turn_number,
            )
        )


def _query_context_for_session(
    session: InferenceRowStreamSession,
    *,
    scheduler: InferenceRowScheduler,
) -> AnalyticQueryContext:
    from api.analytics.scores.export_services import ScoresExportContext

    load_turn = session.load_scoreboard_turn
    if load_turn is None:

        def load_turn(turn_number: int):
            return session.turn if turn_number == session.turn_number else None

    export_services = dict(session.export_services)
    injected_scores_services = export_services.get(SCORES_ANALYTIC_ID)
    if isinstance(injected_scores_services, ScoresExportContext):
        scores_services = replace(injected_scores_services, scheduler=scheduler)
    else:
        scores_services = ScoresExportContext(scheduler=scheduler)
    export_services[SCORES_ANALYTIC_ID] = scores_services

    return make_analytic_query_context(
        session.turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services=export_services,
    )


def create_inference_row_scheduler(
    *,
    on_held_solutions_updated: OnHeldSolutionsUpdatedCallback | None = None,
    **_deprecated_kwargs: object,
) -> InferenceRowScheduler:
    return InferenceRowScheduler(
        on_held_solutions_updated=on_held_solutions_updated,
        **_deprecated_kwargs,
    )


_scheduler: InferenceRowScheduler | None = None
_scheduler_lock = threading.Lock()


def get_inference_row_scheduler(
    *,
    on_held_solutions_updated: OnHeldSolutionsUpdatedCallback | None = None,
    **_deprecated_kwargs: object,
) -> InferenceRowScheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = create_inference_row_scheduler(
                on_held_solutions_updated=on_held_solutions_updated,
                **_deprecated_kwargs,
            )
        return _scheduler


def reset_inference_row_scheduler_for_tests() -> None:
    """Drop the process-wide scheduler (tests only)."""
    global _scheduler
    from api.analytics.military_score_inference.row_stream_resolution_registry import (
        reset_stream_resolution_registry_for_tests,
    )
    from api.analytics.scores.cancel_fence_store import reset_cancel_fence_store_for_tests
    from api.analytics.scores.known_run_allow_store import reset_known_run_allow_store_for_tests
    from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
    from api.compute.runtime import reset_orchestrators_for_tests

    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown()
        _scheduler = None
    reset_orchestrators_for_tests()
    reset_tier_row_run_registry_for_tests()
    reset_stream_resolution_registry_for_tests()
    reset_cancel_fence_store_for_tests()
    reset_known_run_allow_store_for_tests()
    from api.compute.pools import shutdown_compute_worker_pool_for_tests

    shutdown_compute_worker_pool_for_tests()
