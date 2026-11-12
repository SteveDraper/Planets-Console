"""Process-wide orchestrator adapter for scores inference table stream tier work."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from enum import Enum

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    solve_context,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    GlobalPauseChanged,
    HeldSolutionsUpdated,
    RowComplete,
    TierProgress,
    WorkAccepted,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_resolution import (
    InferenceStreamResolutionMixin,
)
from api.analytics.military_score_inference.inference_stream_scope import (
    InferenceStreamScope,
    scores_root_scope_for_session,
)
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
    PauseRelease,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    wake_inference_table_stream_multiplex,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.scope import ComputeScope
from api.errors import ValidationError
from api.streaming.table_stream.pending_accepts import PendingAccepts
from api.streaming.table_stream.scheduler_orchestrator_attachment import (
    SchedulerOrchestratorAttachment,
)
from api.streaming.table_stream.scope_guard import TableStreamScopeGuard

__all__ = [
    "InferenceRowScheduler",
    "TierLadderRegistration",
    "create_inference_row_scheduler",
    "get_inference_row_scheduler",
    "reset_inference_row_scheduler_for_tests",
]

OnHeldSolutionsUpdatedCallback = Callable[[InferenceRowStreamSession], None]


class TierLadderRegistration(Enum):
    """How ``enqueue_tier_ladder`` registered a RowRun. The RowRun is registered in every case."""

    # The scope's table stream owns the run: a stream binding exists and an
    # accept is pending. The caller submits it with ``accept_pending_run``.
    STREAM_BOUND = "stream_bound"
    # No table stream owns the run: there was no stream token, or the token no
    # longer owns the scope. A deferred scores node for the scope is woken, and
    # the run is never accepted by a stream.
    BACKGROUND = "background"
    # The owning stream is globally paused: a held submission is queued, and
    # clearing pause (``resume_globally`` or a stream switch) submits it.
    HELD = "held"
    # The scheduler was built with ``defer_orchestrator_submit`` (tests and
    # diagnostics): the run is registered, taking the scope index as stream
    # ownership decides, and nothing is bound, accepted, held or woken.
    SUBMIT_DEFERRED = "submit_deferred"


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
        # Scope index only -- RowRun objects live in ``tier_row_run_registry``.
        self._runs: dict[str, ComputeScope] = {}
        # Execution identity for cancel abort, captured after submit/wake *outside*
        # the scheduler lock. ``cancel_run`` must never call into the orchestrator
        # while holding ``_lock`` (scheduler → orch nests ABBA with orch drain →
        # scheduler listeners, which also hangs diagnostics snapshot on orch).
        self._execution_generation_by_run_id: dict[str, int] = {}
        # RLock: a scope-outcome listener running on the dispatch caller can re-enter
        # this scheduler. Do not hold the lock across orchestrator-condition acquires
        # (abort_scope, execution generation).
        self._lock = threading.RLock()
        self._scope_guard = TableStreamScopeGuard[InferenceStreamScope]()
        self._stream_bindings: dict[str, InferenceStreamOrchestratorBinding] = {}
        self._globally_paused = False
        self._held_initial_submissions: list[HeldTierSubmission] = []
        self._pending_accepts = PendingAccepts()
        # Listener and pause gate are scheduler-lifetime. Do not register here:
        # ``get_inference_row_scheduler`` holds ``_scheduler_lock`` across
        # construction, and ``ensure_registered`` takes the orchestrator
        # condition. Call sites register outside ``_lock``. The gate reads
        # ``_globally_paused``.
        self._orchestrator_attachment = SchedulerOrchestratorAttachment(
            on_scope_outcome=self._on_orchestrator_scope_outcome,
            dispatch_gate=self._pause_dispatch_gate,
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
        """Return whether scores@N should wipe+reschedule after one fleet ledger persist.

        Own-DAG elision (#204): when scores is already a non-terminal dependent of
        this fleet scope on the same orchestrator DAG (``waiting_deps``, ``ready``,
        ``running``, or ``parked``), skip **both** durable wipe and in-place
        reschedule -- first-pass dataflow is DependencyOutputs. Elision peeks the
        stream binding's orchestrator when a scores stream is open, otherwise the
        process compute orchestrator (cold export-ensure DAG with no stream).
        Ambient / external consumers still wipe then reschedule (reschedule is a
        no-op without a stream controller).

        Orchestrator peeks run outside the scheduler lock so adapters never read
        the live ``nodes`` map under that lock.
        """
        from api.compute.runtime import get_compute_orchestrator

        with self._lock:
            binding = self._stream_binding_for_scope_locked(scope)
            scores_scope = scope.root_scope(event.player_id)
            fleet_scope = self._fleet_scope_for_event(scope, event)
            orchestrator = binding.orchestrator if binding is not None else None

        if orchestrator is None:
            orchestrator = get_compute_orchestrator()

        if self._should_skip_reschedule_for_fleet_persist(
            orchestrator,
            scores_scope,
            fleet_scope,
            event,
        ):
            return False

        with self._lock:
            invalidate_row()
        return True

    def _should_skip_reschedule_for_fleet_persist(
        self,
        orchestrator: ComputeOrchestrator,
        scores_scope: ComputeScope,
        fleet_scope: ComputeScope,
        event: FleetLedgerPersistedEvent,
    ) -> bool:
        """Return whether to skip wipe+reschedule for this fleet persist notification.

        Own-DAG fleet persist notifications fire only after the fleet node is
        ``complete`` (deferred until after ``_complete_node``). Skip when scores is
        a non-terminal dependent of that fleet scope and the completed fleet
        node's materialization version matches the notification. A persist while
        fleet is still non-terminal, or scores that does not depend on this fleet
        node, is treated as external and must wipe+reschedule.
        """
        scores_view = orchestrator.peek_scope_view(scores_scope)
        if scores_view is None or scores_view.is_terminal:
            return False
        if fleet_scope not in scores_view.dependency_scopes:
            return False

        fleet_view = orchestrator.peek_scope_view(fleet_scope)
        if fleet_view is None or fleet_view.state != "complete":
            return False

        return not self._fleet_versions_conflict(fleet_view.result_wire, event)

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
        fleet_result_wire: object | None,
        event: FleetLedgerPersistedEvent,
    ) -> bool:
        from api.analytics.fleet.serialization import (
            materialization_version_from_fleet_compute_result_wire,
        )

        stream_version = materialization_version_from_fleet_compute_result_wire(fleet_result_wire)
        if stream_version is None:
            return False
        return stream_version != event.materialization_version

    def row_run_for_player(
        self,
        scope: InferenceStreamScope,
        player_id: int,
    ) -> RowRun | None:
        """Return the live ``REGISTERED`` RowRun for this player, if any.

        Reads the registry's scope index, so a stale duplicate run for the same
        scope never shadows the indexed run. ``DETACHED`` shells (and cancelled
        admissions with no shell) are not re-attached here.
        """
        from api.analytics.scores.tier_row_run_registry import get_row_run_for_scope

        return get_row_run_for_scope(scope.root_scope(player_id))

    def global_pause_status(self, scope: InferenceStreamScope) -> dict[str, object]:
        with self._lock:
            inputs = self._global_pause_status_inputs_locked(scope)
        return self._global_pause_status_from_inputs(scope, inputs)

    def _global_pause_status_inputs_locked(
        self,
        scope: InferenceStreamScope,
    ) -> dict[str, object]:
        """Scheduler-owned pause fields. Caller holds ``self._lock``."""
        active_scope = self._scope_guard.active_scope
        scope_matches = active_scope == scope
        return {
            "scope_matches": scope_matches,
            "globally_paused": self._globally_paused,
            "held_base_jobs": len(self._held_initial_submissions),
            "active_session_count": len(self._runs) if scope_matches else 0,
            "active_scope_wire": (
                {
                    "gameId": active_scope.game_id,
                    "perspective": active_scope.perspective,
                    "turn": active_scope.turn_number,
                }
                if active_scope is not None
                else None
            ),
            "root_scopes": tuple(self._runs.values()),
            "orchestrators": tuple(
                binding.orchestrator for binding in self._stream_bindings.values()
            ),
        }

    def _global_pause_status_from_inputs(
        self,
        scope: InferenceStreamScope,
        inputs: dict[str, object],
    ) -> dict[str, object]:
        """Build pause status wire; may peek orchestrators (no scheduler lock)."""
        scope_matches = bool(inputs["scope_matches"])
        globally_paused = bool(inputs["globally_paused"])
        held_jobs = int(inputs["held_base_jobs"])
        held_continuations = 0
        if globally_paused and scope_matches:
            root_scopes = inputs["root_scopes"]
            orchestrators = inputs["orchestrators"]
            if isinstance(root_scopes, tuple) and isinstance(orchestrators, tuple):
                for orchestrator in orchestrators:
                    ready_steps = orchestrator.peek_ready_step_indexes(root_scopes)
                    for step_index in ready_steps.values():
                        if step_index == 0:
                            held_jobs += 1
                        else:
                            held_continuations += 1
        return {
            "gameId": scope.game_id,
            "perspective": scope.perspective,
            "turn": scope.turn_number,
            "paused": globally_paused and scope_matches,
            "activeScope": inputs["active_scope_wire"],
            "heldJobCount": held_jobs if scope_matches else 0,
            "heldContinuationCount": held_continuations if scope_matches else 0,
            "activeSessionCount": inputs["active_session_count"],
        }

    def _require_active_stream_for_scope_locked(self, scope: InferenceStreamScope) -> None:
        if not self._scope_guard.has_active_table_stream or self._scope_guard.active_scope != scope:
            raise ValidationError(
                "Global pause requires an active inference table stream for this scope."
            )

    def pause_globally(self, scope: InferenceStreamScope) -> dict[str, object]:
        """Soft pause: hold tier_solve dispatch; in-flight tier work is not cancelled.

        The pause gate is installed on the live process orchestrator before this
        takes the scheduler lock, so a replaced orchestrator still honors pause.
        """
        self._orchestrator_attachment.ensure_registered()
        with self._lock:
            self._require_active_stream_for_scope_locked(scope)
            already_paused = self._globally_paused
            self._globally_paused = True
            if not already_paused:
                self._broadcast_global_pause_locked(paused=True)
            inputs = self._global_pause_status_inputs_locked(scope)
        return self._global_pause_status_from_inputs(scope, inputs)

    def resume_globally(self, scope: InferenceStreamScope) -> dict[str, object]:
        """Clear global pause and release the work it held."""
        with self._lock:
            self._require_active_stream_for_scope_locked(scope)
            release = self._clear_global_pause_locked()
            inputs = self._global_pause_status_inputs_locked(scope)
        self._apply_pause_release(release)
        return self._global_pause_status_from_inputs(scope, inputs)

    def _clear_global_pause_locked(self) -> PauseRelease:
        """Clear global pause and take every held submission. Caller holds ``self._lock``.

        Clearing pause releases held work: the caller passes the result to
        ``_apply_pause_release`` once the lock is released. A caller that drops
        it instead documents why the held work must not run.
        """
        if not self._globally_paused:
            return PauseRelease()
        self._globally_paused = False
        self._broadcast_global_pause_locked(paused=False)
        held = tuple(self._held_initial_submissions)
        self._held_initial_submissions.clear()
        return PauseRelease(was_paused=True, held=held)

    def _apply_pause_release(self, release: PauseRelease) -> None:
        """Submit released held work, then dispatch what the pause gate held.

        Caller must not hold ``self._lock``: submit and dispatch take the
        orchestrator condition. The dispatch pass runs on the orchestrator the
        pause gate is registered on.
        """
        if not release.was_paused:
            return
        orchestrator = self._orchestrator_attachment.ensure_registered()
        for held in release.held:
            self._submit_tier_solve_locked(held.binding, held.root_scope)
        orchestrator.dispatch_ready_work()

    def unregister_session(self, run_id: str) -> None:
        with self._lock:
            self._remove_run_locked(run_id)

    def forget_runs(self, run_ids: tuple[str, ...]) -> None:
        """Drop runs the tier registry already retired from the scheduler's run maps.

        Pops ``_runs``, the cached execution generations and pending accepts
        only. Held submissions stay: they are keyed by root scope, which the
        scope's surviving run shares.
        """
        with self._lock:
            for run_id in run_ids:
                self._runs.pop(run_id, None)
                self._execution_generation_by_run_id.pop(run_id, None)
            self._pending_accepts.discard_all(run_ids)

    def enqueue_tier_ladder(
        self,
        session: InferenceRowStreamSession,
        *,
        orchestration: InferenceStreamOrchestration | None = None,
        stream_token: str | None = None,
    ) -> TierLadderRegistration:
        """Register one tier ladder RowRun and decide, once, which stream owns it.

        The RowRun is always registered. Under ``self._lock`` the owning stream
        is ``stream_token`` while that token still owns the scope, decided
        before the run is registered. With an owner the run is
        ``STREAM_BOUND`` (the caller runs ``accept_pending_run``) or ``HELD``
        while globally paused. With no owner the run is ``BACKGROUND`` and the
        scope's deferred scores node is woken after the lock: that covers no
        token at all, whatever stream is active, and a token that lost the
        scope to another stream. A submit-deferred scheduler returns
        ``SUBMIT_DEFERRED`` after registering.

        Ownership also decides the scope index, so the scope's next ladder
        claim stamps the stream's run: an owned run takes the index, and a
        background run takes it only when no ``REGISTERED`` run holds it. A
        background run never displaces a stream's run. It stays registered
        beside it as a duplicate until the scope's next ladder claim retires
        it (``claim_tier_ladder`` hand-over). Duplicates come from an export
        admit that checked for a run before its fleet I/O, a connect admission
        that lost its scope on a T -> T' -> T toggle, and an admit at a scope a
        stream has claimed in ``begin_scope`` but not yet attached its
        controller to: an export admit passes the token of the stream attached
        at its own scope, so that admit has none and registers ``BACKGROUND``,
        and the stream's own admission then takes the index.
        """
        from api.analytics.scores.tier_row_run_registry import ScopeIndexPolicy, register_row_run

        with self._lock:
            owning_token = (
                stream_token
                if stream_token is not None
                and self._scope_guard.owns_table_stream_locked(stream_token)
                else None
            )
            row_run = RowRun(session)
            register_row_run(
                row_run,
                scope_index=(
                    ScopeIndexPolicy.TAKE
                    if owning_token is not None
                    else ScopeIndexPolicy.TAKE_IF_VACANT
                ),
                orchestration=orchestration,
            )
            self._register_tier_callbacks_for_run(row_run)
            root_scope = scores_root_scope_for_session(session)
            self._runs[session.run_id] = root_scope
            if self._defer_orchestrator_submit:
                return TierLadderRegistration.SUBMIT_DEFERRED
            if owning_token is not None:
                binding = self._binding_for_stream_locked(owning_token, session=session)
                if self._globally_paused:
                    self._held_initial_submissions.append(
                        HeldTierSubmission(
                            stream_token=owning_token, binding=binding, root_scope=root_scope
                        )
                    )
                    return TierLadderRegistration.HELD
                # Accept is separate so connect can paint every player before submit.
                # Submit stays outside this lock: it drains listeners that re-enter
                # the scheduler.
                self._pending_accepts.register(
                    session.run_id,
                    self._tier_accept(binding, root_scope, session.run_id),
                )
                return TierLadderRegistration.STREAM_BOUND
        # No stream submits this run, so a soft-parked scores node needs an
        # explicit force_fresh wake.
        self._orchestrator_attachment.ensure_registered()
        self._wake_deferred_scores_after_row_run_adopt(root_scope, session)
        return TierLadderRegistration.BACKGROUND

    def accept_pending_run(self, run_id: str) -> None:
        """Submit a run whose accept is still pending. A second call is a no-op."""
        self._pending_accepts.accept(run_id)

    def _tier_accept(
        self,
        binding: InferenceStreamOrchestratorBinding,
        root_scope: ComputeScope,
        run_id: str,
    ) -> Callable[[], None]:
        def accept() -> None:
            with self._lock:
                row_run = self._adapter_row_run(run_id)
                if row_run is None or row_run.session.cancel_token.is_cancelled():
                    return
            self._orchestrator_attachment.ensure_registered()
            self._submit_tier_solve_locked(binding, root_scope)

        return accept

    def cancel_row_run(self, run_id: str) -> None:
        """Cancel one row run and drop its pending accept."""
        with self._lock:
            self._pending_accepts.discard(run_id)
        self.cancel_run(run_id)

    def clear_global_pause_for_replaced_rows(self, scope: InferenceStreamScope) -> None:
        """Clear global pause at the active ``scope`` before its rows are cancelled and replaced.

        The caller then cancels and reschedules every row at ``scope``. Each
        held submission belongs to one of those rows, so it is dropped, not
        released: submitting it would only start work the cancel aborts, and
        the replacement rows submit themselves once pause is clear. The
        dispatch pass still runs for the nodes the pause gate held.
        """
        with self._lock:
            if self._scope_guard.active_scope != scope:
                return
            release = self._clear_global_pause_locked()
        self._apply_pause_release(replace(release, held=()))

    def shutdown(self) -> None:
        """Reset adapter state; safe for test teardown after dropping a service stack."""
        self._orchestrator_attachment.shutdown()
        with self._lock:
            self._invalidate_retained_state_locked()

    def deliver_held_solutions_to_stream(self, session: InferenceRowStreamSession) -> bool:
        """Queue the run's held top-K on its stream and wake the multiplex.

        Stream-only: no inference evidence is announced, so no fleet or scores
        epoch moves. Returns False, delivering nothing, when the run holds no
        solutions or its accelerated segment does not stream solutions. The
        observation and segment come from the run's ladder orchestration.
        """
        row_run = self._adapter_row_run(session.run_id)
        if row_run is None:
            return False
        state = row_run.ladder_state
        if state is None or state.catalog is None or not state.merged_solutions:
            return False
        orchestration = row_run.orchestration
        segment_id: str | None = None
        if orchestration is not None:
            if not orchestration.should_emit_streaming_solutions():
                return False
            segment_id = orchestration.current_segment().segment_id
        observation, _turn = solve_context(row_run)
        session.event_queue.put(
            HeldSolutionsUpdated(
                solutions=tuple(state.merged_solutions),
                catalog=state.catalog,
                observation=observation,
                segment_id=segment_id,
            )
        )
        self._wake_multiplex_for_session(session)
        return True

    def _emit_held_solutions(self, session: InferenceRowStreamSession) -> None:
        """Deliver an admitted solution's held top-K, then announce the inference evidence."""
        if self.deliver_held_solutions_to_stream(session) and (
            self._on_held_solutions_updated is not None
        ):
            self._on_held_solutions_updated(session)

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
                emit_held_solutions=lambda: self._emit_held_solutions(session),
            )

        register_tier_callbacks(row_run.run_id, callbacks())

    def _binding_for_stream_locked(
        self,
        stream_token: str,
        *,
        session: InferenceRowStreamSession,
    ) -> InferenceStreamOrchestratorBinding:
        """Install a stream binding. Caller holds ``self._lock``.

        The binding stores query context only. The pause gate is registered once
        for the scheduler, not per stream.
        """
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
        return binding

    def _wake_deferred_scores_after_row_run_adopt(
        self,
        root_scope: ComputeScope,
        session: InferenceRowStreamSession,
    ) -> None:
        """Wake a deferred scores node after background RowRun register."""
        from api.analytics.scores.compute_orchestration import wake_scores_scope
        from api.analytics.scores_defer_wake import ScoresWakeReason

        wake_scores_scope(
            root_scope,
            ctx=_query_context_for_session(session, scheduler=self),
            reason=ScoresWakeReason.ROW_RUN_ADOPTED,
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
        from api.analytics.scores.compute_orchestration import wake_scores_scope
        from api.analytics.scores_defer_wake import ScoresWakeReason

        # force_fresh may replace a prior empty/admission terminal. Reopen the multiplex
        # row so progress drains and a later RowComplete can upgrade the soft terminal.
        self._reopen_stream_row_for_force_fresh(root_scope)
        wake_scores_scope(
            root_scope,
            ctx=binding.query_context,
            reason=ScoresWakeReason.STREAM_RESCHEDULED,
            orchestrator=binding.orchestrator,
        )
        self._remember_execution_generation_for_scope(
            root_scope,
            orchestrator=binding.orchestrator,
        )
        self._emit_work_accepted(root_scope)

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

    def _pause_dispatch_gate(self, node: object) -> bool:
        from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE_PROFILE_INDEX

        if not self._globally_paused:
            return True
        if node.scope.analytic_id != SCORES_ANALYTIC_ID:
            return True
        return node.profile_step_index != SCORES_TIER_SOLVE_PROFILE_INDEX

    @staticmethod
    def _row_complete_from_result_wire(result_wire: object | None) -> RowComplete | None:
        if not isinstance(result_wire, dict):
            return None
        row_complete = result_wire.get("rowComplete")
        if isinstance(row_complete, RowComplete):
            return row_complete
        return None

    def _emit_work_accepted(self, root_scope: ComputeScope) -> None:
        with self._lock:
            sessions = []
            for run_id, scope in self._runs.items():
                if scope != root_scope:
                    continue
                row_run = self._adapter_row_run(run_id)
                if row_run is None or row_run.session.cancel_token.is_cancelled():
                    continue
                sessions.append(row_run.session)
        for session in sessions:
            session.event_queue.put(WorkAccepted())
            self._wake_multiplex_for_session(session)

    @staticmethod
    def _wake_multiplex_for_session(session: InferenceRowStreamSession) -> None:
        wake_inference_table_stream_multiplex(InferenceStreamScope.from_session(session))


def _query_context_for_session(
    session: InferenceRowStreamSession,
    *,
    scheduler: InferenceRowScheduler,
) -> AnalyticQueryContext:
    """Bind the stream scheduler onto scores export services without dropping ``ensure_turn``.

    Production streams pass the factory-built leader ctx on the session. This
    replaces only the scheduler-bound scores bundle. Admit raises if that ctx
    is missing -- tests that never submit a DAG must attach a ctx at the test
    site rather than reconstructing from the session bag here.
    """
    from api.analytics.scores.export_services import ScoresExportContext

    ctx = session.query_context
    if ctx is None:
        raise ValueError(
            "scores table-stream admit requires AnalyticQueryContext; "
            "production must pass the TurnAnalyticService factory ctx"
        )

    export_services = dict(ctx.export_services)
    injected_scores_services = export_services.get(SCORES_ANALYTIC_ID)
    if isinstance(injected_scores_services, ScoresExportContext):
        scores_services = replace(injected_scores_services, scheduler=scheduler)
    else:
        scores_services = ScoresExportContext(scheduler=scheduler)
    export_services[SCORES_ANALYTIC_ID] = scores_services
    return replace(ctx, export_services=export_services)


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


def inference_row_scheduler_if_initialized() -> InferenceRowScheduler | None:
    """Return the process scheduler when already constructed (no lazy init)."""
    return _scheduler


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
    from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
    from api.compute.runtime import reset_orchestrators_for_tests
    from api.streaming.table_stream.row_stream_resolution_registry import (
        reset_stream_resolution_registry_for_tests,
    )

    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown()
        _scheduler = None
    reset_orchestrators_for_tests()
    reset_tier_row_run_registry_for_tests()
    reset_stream_resolution_registry_for_tests()
    from api.compute.pools import shutdown_compute_worker_pool_for_tests

    shutdown_compute_worker_pool_for_tests()
