"""Process-wide orchestrator adapter for scores inference table stream tier work."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
from api.analytics.military_score_inference.inference_row_runner import InferenceTierJobCallbacks
from api.analytics.military_score_inference.inference_stream_domain_events import (
    GlobalPauseChanged,
    HeldSolutionsUpdated,
    RowComplete,
    RowFailed,
    TierProgress,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    deliver_inference_domain_event_to_open_stream,
    wake_inference_table_stream_multiplex,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
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

# Shared abort detail so node-complete listeners can ignore intentional cancels
# (must not deliver RowFailed / orphan terminals to an open multiplex).
_SCORES_ROW_RUN_CANCELLED_MESSAGE = "scores inference row run cancelled"


@dataclass
class _InferenceStreamOrchestratorBinding:
    orchestrator: object
    unregister_listener: Callable[[], None]
    query_context: AnalyticQueryContext
    unregister_dispatch_gate: Callable[[], None] | None = None


@dataclass(frozen=True)
class _HeldTierSubmission:
    stream_token: str
    root_scope: ComputeScope


class InferenceRowScheduler:
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
        # RLock: adapter methods hold this lock across orchestrator calls. When resume_globally
        # calls _dispatch_ready_orchestrator_work_locked, dispatch_ready_work drains post-lock
        # callbacks in the caller thread and the node-complete listener
        # (_on_orchestrator_node_complete, _finalize_row_run) can re-acquire the lock on that
        # thread. pause_globally shares the same lock while updating dispatch gates. Production
        # tier_solve uses the thread pool backend, so listener completion is usually async rather
        # than synchronous in the dispatch caller.
        self._lock = threading.RLock()
        self._scope_guard = TableStreamScopeGuard[InferenceStreamScope]()
        self._stream_bindings: dict[str, _InferenceStreamOrchestratorBinding] = {}
        self._globally_paused = False
        self._held_initial_submissions: list[_HeldTierSubmission] = []
        # run_ids that already emitted a terminal stream event; used so a late peer
        # failure cannot clobber an earlier successful completion for the same row.
        self._terminal_stream_events_delivered: set[str] = set()
        from api.compute.scope_terminal_fanout import register_process_scope_terminal_listener

        # Peer bindings (fleet DAG) may complete scores scopes without this
        # scheduler's local orchestrator listener. Fan-out delivers those terminals.
        self._unregister_scope_terminal = register_process_scope_terminal_listener(
            self._on_orchestrator_node_complete,
            analytic_id=SCORES_ANALYTIC_ID,
        )

    def begin_scope(self, scope: InferenceStreamScope) -> str:
        with self._lock:
            return self._scope_guard.begin_scope_locked(
                scope,
                on_same_scope_preempt=self._preempt_active_table_stream_locked,
                on_scope_change=self._invalidate_retained_state_locked,
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
    ) -> _InferenceStreamOrchestratorBinding | None:
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
        """Return whether to skip in-place reschedule for this fleet persist notification."""
        from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID

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
        fleet_scope = ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn=event.fleet_turn,
            player_id=event.player_id,
        )
        scores_node = binding.orchestrator.nodes.get(scores_scope)
        if scores_node is None or scores_node.state != "waiting_deps":
            return False
        if fleet_scope not in scores_node.dependency_scopes:
            return False

        fleet_node = binding.orchestrator.nodes.get(fleet_scope)
        if fleet_node is None:
            return False

        if (
            event.source_context_id is not None
            and self._fleet_persist_source_matches_stream_binding(
                binding,
                event.source_context_id,
            )
        ):
            return fleet_node.result_wire is not None and not self._fleet_versions_conflict(
                fleet_node,
                event,
            )

        if fleet_node.state in {"waiting_deps", "ready", "running"}:
            if (
                event.source_context_id is not None
                and self._fleet_persist_source_matches_stream_binding(
                    binding,
                    event.source_context_id,
                )
            ):
                return True
            return False

        if fleet_node.state == "complete":
            return not self._fleet_versions_conflict(fleet_node, event)

        return False

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

    @staticmethod
    def _fleet_persist_source_matches_stream_binding(
        binding: _InferenceStreamOrchestratorBinding,
        source_context_id: int,
    ) -> bool:
        """Match orchestrator dep-chain notifications to one stream binding context."""
        if source_context_id == id(binding.query_context):
            return True
        orchestrator = binding.orchestrator
        original_ctx = getattr(orchestrator, "_ctx", None)
        if original_ctx is not None and source_context_id == id(original_ctx):
            return True
        cached_ctx = getattr(orchestrator, "_cached_ctx", None)
        return cached_ctx is not None and source_context_id == id(cached_ctx)

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

    def end_inference_stream(
        self,
        scope: InferenceStreamScope,
        sessions: tuple[InferenceRowStreamSession, ...],
        *,
        stream_token: str,
    ) -> None:
        """Cancel all row runs for a table stream and clear global pause on disconnect."""
        remaining_bindings: tuple[_InferenceStreamOrchestratorBinding, ...] = ()
        clear_pause_gates = False
        with self._lock:
            owns_scope = self._scope_guard.end_table_stream_locked(scope, stream_token)
            for session in sessions:
                session.cancel_token.cancel()
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

    def cancel_run(self, run_id: str) -> None:
        abort_scope: ComputeScope | None = None
        with self._lock:
            row_run = self._adapter_row_run(run_id)
            root_scope = self._runs.get(run_id)
            if row_run is not None:
                row_run.session.cancel_token.cancel()
            self._remove_run_locked(run_id)
            abort_scope = root_scope
        # Abort outside the scheduler lock: ``abort_scope`` drains node-complete
        # listeners that may deliver stream events (controller ``stream_lock``) or
        # call ``owns_table_stream`` (needs this lock). Holding ``_lock`` here ABBA /
        # self-deadlocks with ``reschedule_row`` (stream_lock -> cancel -> abort).
        if abort_scope is not None:
            self._abort_orchestrator_scopes(abort_scope)

    def enqueue_tier_ladder(
        self,
        session: InferenceRowStreamSession,
        *,
        orchestration: InferenceStreamOrchestration | None = None,
        stream_token: str | None = None,
    ) -> None:
        submit_binding: _InferenceStreamOrchestratorBinding | None = None
        submit_scope: ComputeScope | None = None
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
            if resolved_token is None:
                return
            if self._scope_guard.active_table_stream_token != resolved_token:
                return
            if self._defer_orchestrator_submit:
                return
            binding = self._binding_for_stream_locked(resolved_token, session=session)
            if self._globally_paused:
                self._held_initial_submissions.append(
                    _HeldTierSubmission(stream_token=resolved_token, root_scope=root_scope)
                )
                return
            # Submit outside the scheduler lock: ``orchestrator.submit`` drains diagnostics
            # listeners that must not nest scheduler <-> orchestrator locks.
            submit_binding = binding
            submit_scope = root_scope
        if submit_binding is not None and submit_scope is not None:
            self._submit_tier_solve_locked(submit_binding, submit_scope)

    def cancel_row_run(self, run_id: str) -> None:
        """Cancel one row run."""
        self.cancel_run(run_id)

    def clear_global_pause_for_scope(self, scope: InferenceStreamScope) -> None:
        bindings: tuple[_InferenceStreamOrchestratorBinding, ...] = ()
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
        unregister = getattr(self, "_unregister_scope_terminal", None)
        if callable(unregister):
            unregister()
            self._unregister_scope_terminal = None
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
    ) -> _InferenceStreamOrchestratorBinding:
        from api.compute.runtime import orchestrator_for_context

        existing = self._stream_bindings.get(stream_token)
        if existing is not None:
            return existing
        query_ctx = _query_context_for_session(session, scheduler=self)
        orchestrator = orchestrator_for_context(query_ctx)
        unregister = orchestrator.register_node_complete_listener(
            lambda scope, node: self._on_orchestrator_node_complete(scope, node)
        )
        binding = _InferenceStreamOrchestratorBinding(
            orchestrator=orchestrator,
            unregister_listener=unregister,
            query_context=query_ctx,
        )
        self._stream_bindings[stream_token] = binding
        self._apply_dispatch_gates_locked()
        return binding

    def _on_orchestrator_node_complete(
        self,
        scope: ComputeScope,
        node: object,
    ) -> None:
        if scope.analytic_id != SCORES_ANALYTIC_ID:
            return
        if scope.turn == "*" or not isinstance(scope.turn, int):
            return
        if scope.player_id == "*" or not isinstance(scope.player_id, int):
            return
        # Intentional row-run cancel aborts in-flight DAG nodes. Do not fail (or
        # orphan-complete) the open multiplex -- reschedule will admit a replacement.
        if self._is_cancel_abort_failure(node):
            return

        wire_run_id = self._run_id_from_result_wire(getattr(node, "result_wire", None))
        sibling_still_active = self._scope_has_live_nonterminal_work(scope)

        with self._lock:
            matching_run_ids = [
                run_id
                for run_id, root_scope in self._runs.items()
                if root_scope.player_id == scope.player_id
                and root_scope.game_id == scope.game_id
                and root_scope.perspective == scope.perspective
                and scope.turn == root_scope.turn
            ]
            if wire_run_id is not None:
                matching_run_ids = [run_id for run_id in matching_run_ids if run_id == wire_run_id]

        for run_id in matching_run_ids:
            row_run = self._adapter_row_run(run_id)
            if row_run is None:
                # Stale scheduler entry (registry already dropped). Remove it so the
                # ensure-terminal fallback below can finish an open multiplex row.
                with self._lock:
                    self._remove_run_locked(run_id)
                continue
            session = row_run.session
            deliver_session = self._open_stream_session_for_scope(scope) or session
            if node.state == "failed":
                if sibling_still_active:
                    # Peer binding (e.g. stream_attached) still owns the shared RowRun.
                    # Do not fail the stream or unregister -- the peer may still succeed.
                    continue
                if deliver_session.run_id in self._terminal_stream_events_delivered:
                    # Peer already delivered success; just release when last binding ends.
                    self._finalize_row_run(session)
                    continue
                detail = (
                    str(node.error) if node.error is not None else "Inference tier solve failed"
                )
                self._deliver_stream_terminal(
                    deliver_session,
                    RowFailed(detail=detail),
                )
                self._finalize_row_run(session)
                continue
            if node.state != "complete":
                continue
            row_complete = self._row_complete_from_result_wire(node.result_wire)
            if row_complete is None:
                if sibling_still_active:
                    continue
                if deliver_session.run_id in self._terminal_stream_events_delivered:
                    self._finalize_row_run(session)
                    continue
                self._deliver_stream_terminal(
                    deliver_session,
                    RowFailed(detail="Inference tier solve completed without row payload"),
                )
                self._finalize_row_run(session)
                continue
            if deliver_session.run_id not in self._terminal_stream_events_delivered:
                self._deliver_stream_terminal(deliver_session, row_complete)
            if sibling_still_active:
                # Keep the process-wide RowRun registered until the last binding
                # for this scope reaches a terminal state (background + stream share it).
                continue
            self._finalize_row_run(session)

        # Always re-check after matching-run handling. Empty / idempotent tier_solve can
        # leave the DAG terminal while multiplex still waits (stale ``_runs``, cancelled
        # session skip, or peer unregister). Do not rely on matching_run_ids alone.
        if getattr(node, "state", None) in {"complete", "failed"} and not (
            self._scope_has_live_nonterminal_work(scope)
        ):
            self._deliver_orphan_stream_terminal_if_needed(scope, node)

    def _deliver_stream_terminal(
        self,
        session: InferenceRowStreamSession,
        event: RowComplete | RowFailed,
    ) -> None:
        """Deliver one terminal domain event at most once per stream session run_id."""
        with self._lock:
            if session.run_id in self._terminal_stream_events_delivered:
                return
            self._terminal_stream_events_delivered.add(session.run_id)
        deliver_inference_domain_event_to_open_stream(session, event)

    def _open_stream_session_for_scope(
        self,
        scope: ComputeScope,
    ) -> InferenceRowStreamSession | None:
        """Return the open multiplex session for ``scope``, if any.

        Prefer this over a scheduler ``RowRun.session``: ensure/background can register a
        different session than the table stream adopted, and delivering to the wrong
        queue leaves multiplex waiting forever while the UI stays in-progress.
        """
        from api.analytics.military_score_inference.inference_table_stream_registry import (
            controller_for_scope,
        )

        player_id = scope.player_id
        turn_number = scope.turn
        if not isinstance(player_id, int) or not isinstance(turn_number, int):
            return None
        controller = controller_for_scope(
            InferenceStreamScope(
                game_id=scope.game_id,
                perspective=scope.perspective,
                turn_number=turn_number,
            )
        )
        if controller is None:
            return None
        scheduled = controller.scheduled_rows.get(player_id)
        if scheduled is None:
            return None
        return scheduled.session

    def _deliver_orphan_stream_terminal_if_needed(
        self,
        scope: ComputeScope,
        node: object,
    ) -> None:
        """Finish an open multiplex row when the DAG scope is fully terminal.

        Covers: matching-run path missed the stream session; peer unregistered the
        RowRun; stale ``_runs`` entries were swept; cancelled sessions that would
        otherwise be marked finished by multiplex without a wire event; empty
        ``tier_solve`` skips on a peer binding with no ``rowComplete`` payload.
        """
        session = self._open_stream_session_for_scope(scope)
        if session is None:
            return
        from api.analytics.military_score_inference.inference_table_stream_registry import (
            controller_for_scope,
        )

        controller = controller_for_scope(
            InferenceStreamScope(
                game_id=scope.game_id,
                perspective=scope.perspective,
                turn_number=scope.turn if isinstance(scope.turn, int) else -1,
            )
        )
        if controller is None:
            return
        with self._lock:
            if session.run_id in self._terminal_stream_events_delivered:
                return
            # Claim delivery before emit so concurrent peer notifications cannot double-send.
            self._terminal_stream_events_delivered.add(session.run_id)

        row_complete = self._row_complete_from_result_wire(getattr(node, "result_wire", None))
        if row_complete is not None:
            event: RowComplete | RowFailed | None = row_complete
        elif getattr(node, "state", None) == "failed":
            detail = (
                str(node.error)
                if getattr(node, "error", None) is not None
                else "Inference tier solve failed"
            )
            event = RowFailed(detail=detail)
        elif self._deliver_admission_wire_terminal(controller, session):
            with self._lock:
                self._remove_run_locked(session.run_id)
            return
        else:
            event = RowFailed(detail="Inference tier solve completed without row payload")

        if session.run_id in controller.finished_run_ids:
            from api.analytics.military_score_inference.inference_stream_rows import (
                tag_inference_stream_event,
            )
            from api.transport.inference_stream_wire import domain_event_to_wire_events

            with controller.stream_lock:
                for wire in domain_event_to_wire_events(
                    event,
                    observation=session.observation,
                    turn=session.turn,
                    fleet_torp_input_status=session.fleet_torp_input_status,
                ):
                    controller.pending_wire_events.append(
                        tag_inference_stream_event(wire, player_id=session.player_id)
                    )
            controller.wake_multiplex.set()
        else:
            deliver_inference_domain_event_to_open_stream(session, event)
        with self._lock:
            self._remove_run_locked(session.run_id)

    def _deliver_admission_wire_terminal(
        self,
        controller: object,
        session: InferenceRowStreamSession,
    ) -> bool:
        """Push immediate/cached admission wire when peer complete has no row payload.

        Returns True when a client-visible terminal was delivered from admission.
        """
        from api.analytics.military_score_inference.inference_stream_rows import (
            CachedCompleteRowAdmission,
            ImmediateRowAdmission,
            tag_inference_stream_event,
        )

        resolve = getattr(controller, "resolve_row_admission", None)
        if not callable(resolve):
            return False
        admission = resolve(session.player_id)
        wires: list[dict[str, object]] = []
        if isinstance(admission, ImmediateRowAdmission):
            wires = [
                tag_inference_stream_event(event, player_id=session.player_id)
                for event in admission.events
            ]
        elif isinstance(admission, CachedCompleteRowAdmission) and admission.event is not None:
            wires = [
                tag_inference_stream_event(admission.event, player_id=session.player_id),
            ]
        if not wires:
            return False
        pending = getattr(controller, "pending_wire_events", None)
        finished = getattr(controller, "finished_run_ids", None)
        wake = getattr(controller, "wake_multiplex", None)
        stream_lock = getattr(controller, "stream_lock", None)
        if pending is None or finished is None or wake is None or stream_lock is None:
            return False
        with stream_lock:
            pending.extend(wires)
            finished.add(session.run_id)
        wake.set()
        return True

    def _finalize_row_run(self, session: InferenceRowStreamSession) -> None:
        with self._lock:
            self._remove_run_locked(session.run_id)

    @staticmethod
    def _run_id_from_result_wire(result_wire: object | None) -> str | None:
        if not isinstance(result_wire, dict):
            return None
        run_id = result_wire.get("runId")
        return run_id if isinstance(run_id, str) else None

    @staticmethod
    def _scope_has_live_nonterminal_work(scope: ComputeScope) -> bool:
        """True when any process-wide orchestrator still has non-terminal work for scope.

        Background warm and stream_attached bindings each own an orchestrator; they can
        share one RowRun. Finalizing on the first terminal node unregisters that run and
        races the sibling's continuing ``tier_solve`` wire (missing registered RowRun).
        """
        from api.compute.runtime import live_orchestrators

        for orchestrator in live_orchestrators():
            node = orchestrator.nodes.get(scope)
            if node is not None and node.state not in {"complete", "failed"}:
                return True
        return False

    def _release_stream_binding_locked(
        self,
        binding: _InferenceStreamOrchestratorBinding,
    ) -> None:
        from api.compute.runtime import release_orchestrator_for_context

        if binding.unregister_dispatch_gate is not None:
            binding.unregister_dispatch_gate()
            binding.unregister_dispatch_gate = None
        binding.unregister_listener()
        ctx_id = id(binding.query_context)
        if not any(id(other.query_context) == ctx_id for other in self._stream_bindings.values()):
            release_orchestrator_for_context(binding.query_context)

    def _preempt_active_table_stream_locked(self) -> None:
        self._globally_paused = False
        self._held_initial_submissions.clear()
        for run_id in list(self._runs):
            row_run = self._adapter_row_run(run_id)
            if row_run is not None:
                row_run.session.cancel_token.cancel()
            self._remove_run_locked(run_id)
        self._terminal_stream_events_delivered.clear()
        for stream_token in list(self._stream_bindings):
            binding = self._stream_bindings.pop(stream_token)
            self._release_stream_binding_locked(binding)

    def _invalidate_retained_state_locked(self) -> None:
        self._preempt_active_table_stream_locked()

    def _broadcast_global_pause_locked(self, *, paused: bool) -> None:
        event = GlobalPauseChanged(paused=paused)
        for run_id in self._runs:
            row_run = self._adapter_row_run(run_id)
            if row_run is not None:
                row_run.session.event_queue.put(event)

    def _submit_tier_solve_locked(
        self,
        binding: _InferenceStreamOrchestratorBinding,
        root_scope: ComputeScope,
    ) -> None:
        if self._defer_orchestrator_submit:
            return
        from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE
        from api.compute.orchestrator import ComputeRequest

        binding.orchestrator.submit(
            ComputeRequest(
                scope=root_scope,
                step_kind=SCORES_TIER_SOLVE,
                priority_band="stream_attached",
                force_fresh=True,
            )
        )

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
        bindings: tuple[_InferenceStreamOrchestratorBinding, ...],
        *,
        paused: bool,
    ) -> None:
        """Register or clear pause dispatch gates (must not hold the scheduler lock)."""
        for binding in bindings:
            if paused:
                if binding.unregister_dispatch_gate is None:
                    binding.unregister_dispatch_gate = binding.orchestrator.register_dispatch_gate(
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

    def _remove_run_locked(self, run_id: str) -> None:
        from api.analytics.scores.tier_row_run_registry import unregister_row_run

        root_scope = self._runs.pop(run_id, None)
        unregister_row_run(run_id)
        # Keep ``_terminal_stream_events_delivered`` entries so a late peer binding
        # that finds no matching run cannot orphan-deliver RowFailed after a prior
        # RowComplete for the same run_id.
        if root_scope is None:
            return
        self._held_initial_submissions = [
            held for held in self._held_initial_submissions if held.root_scope != root_scope
        ]

    def _abort_orchestrator_scopes(self, root_scope: ComputeScope) -> None:
        """Fail in-flight orchestrator work for ``root_scope`` after a row-run cancel.

        Without this, a later ``force_fresh`` submit attaches to the still-running node
        and ``tier_solve`` fails with a missing RowRun after unregister.

        Must run without the scheduler lock held (see ``cancel_run``).
        """
        with self._lock:
            bindings = tuple(self._stream_bindings.values())
        for binding in bindings:
            abort = getattr(binding.orchestrator, "abort_scope", None)
            if not callable(abort):
                continue
            abort(
                root_scope,
                RuntimeError(_SCORES_ROW_RUN_CANCELLED_MESSAGE),
            )

    @staticmethod
    def _is_cancel_abort_failure(node: object) -> bool:
        if getattr(node, "state", None) != "failed":
            return False
        error = getattr(node, "error", None)
        return error is not None and _SCORES_ROW_RUN_CANCELLED_MESSAGE in str(error)

    @staticmethod
    def _adapter_row_run(run_id: str) -> RowRun | None:
        from api.analytics.scores.tier_row_run_registry import get_row_run

        return get_row_run(run_id)

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
    from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
    from api.compute.runtime import reset_orchestrators_for_tests
    from api.compute.scope_terminal_fanout import reset_process_scope_terminal_fanout_for_tests

    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown()
        _scheduler = None
    reset_process_scope_terminal_fanout_for_tests()
    reset_orchestrators_for_tests()
    reset_tier_row_run_registry_for_tests()
    from api.compute.pools import shutdown_compute_worker_pool_for_tests

    shutdown_compute_worker_pool_for_tests()
