"""Stream claim, detach and cancel for the scores inference row scheduler.

A stream detaches its own rows when it ends (``detach_inference_stream``).
``begin_scope`` never detaches a run; it resets only stream-owned state.
``cancel_run`` is the explicit cancel path (lifecycle CANCEL, then abort).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.scope import ComputeScope
from api.streaming.table_stream.row_run_admission import RowLifecycleOp

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.analytics.military_score_inference.row_run import RowRun

# Shared abort detail so scope-outcome listeners can ignore intentional cancels
# (must not deliver RowFailed / orphan terminals to an open multiplex).
SCORES_ROW_RUN_CANCELLED_MESSAGE = "scores inference row run cancelled"


@dataclass
class InferenceStreamOrchestratorBinding:
    """One table-stream's leader context on the process-wide singleton orchestrator."""

    orchestrator: ComputeOrchestrator
    query_context: AnalyticQueryContext


@dataclass(frozen=True)
class HeldTierSubmission:
    stream_token: str
    root_scope: ComputeScope


class InferenceStreamTeardownMixin:
    """Claim and end table streams; cancel row runs and abort their orchestrator scopes."""

    def begin_scope(self: InferenceRowScheduler, scope: InferenceStreamScope) -> str:
        """Claim the active table-stream scope and reset stream-owned scheduler state.

        ``begin_scope`` never detaches or cancels a run. A stream detaches its
        own rows when it ends (``detach_inference_stream``, from the connect
        ``finally``), so the replaced stream's rows stay ``REGISTERED`` until
        then and background runs are never touched.

        Under the scheduler lock it resets only stream-owned state:

        - on a scope change, including the first claim, it clears global pause,
          every held submission and every stream binding;
        - on a same-scope preempt, it clears global pause and drops the
          previous stream's held submissions and binding.

        Once pause is cleared no held submission can be resumed. The pause
        gate follows ``_globally_paused``, so a node it held back dispatches on
        the next dispatch pass. The gate and the scope-outcome listener are
        registered after the lock is released, once per process orchestrator.
        """
        with self._lock:
            token = self._scope_guard.begin_scope_locked(
                scope,
                on_same_scope_preempt=self._preempt_active_stream_locked,
                on_scope_change=self._reset_stream_state_locked,
            )
        self._orchestrator_attachment.ensure_registered()
        return token

    def detach_inference_stream(
        self: InferenceRowScheduler,
        scope: InferenceStreamScope,
        sessions: tuple[InferenceRowStreamSession, ...],
        *,
        stream_token: str,
    ) -> None:
        """Detach a table stream's own rows when it ends, without cancelling them.

        This is the only place a stream's rows are detached: each session's
        RowRun goes ``DETACHED`` (shell retained for a late persist), and the
        stream's held submissions and binding are dropped. Clears global pause
        when this stream still owns the scope. The pause gate stays registered
        and follows ``_globally_paused``, so this method does not take the
        orchestrator condition.
        """
        with self._lock:
            owns_scope = self._scope_guard.end_table_stream_locked(scope, stream_token)
            for session in sessions:
                self._remove_run_locked(session.run_id, op=RowLifecycleOp.DETACH)
            self._release_stream_locked(stream_token)
            if owns_scope:
                self._clear_global_pause_for_active_scope_locked(scope)

    def cancel_run(self: InferenceRowScheduler, run_id: str) -> None:
        """Cancel one row run and abort its orchestrator scope when no sibling remains.

        Unlike a stream's end (``detach_inference_stream``), which only detaches
        its rows without cancelling solve work, cancel applies
        :func:`~api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`
        for ``RowLifecycleOp.CANCEL`` (token + compact cancel admission + stream
        CANCELED) then aborts in-flight orchestrator nodes so a later
        ``force_fresh`` submit cannot attach to a still-running node with a
        missing RowRun.

        A duplicate schedule force_fresh-attaches to the survivor's running node
        and caches that same execution generation, then ``cancel_run`` drops the
        duplicate. Aborting that generation fails the shared DAG node the survivor
        still needs. Skip abort while another live run still maps to the scope.
        The last remaining cancel still aborts.
        """
        abort_scope: ComputeScope | None = None
        abort_generation: int | None = None
        with self._lock:
            root_scope = self._runs.get(run_id)
            # Use the generation cached at submit/wake -- never call into the
            # orchestrator while holding the scheduler lock (ABBA with orch drain
            # paths that take this lock, and with diagnostics snapshot on orch).
            abort_generation = self._execution_generation_by_run_id.get(run_id)
            # Lifecycle CANCEL (admission + seal + token) before dropping
            # scheduler maps so late persist still DENYs.
            self._remove_run_locked(run_id, op=RowLifecycleOp.CANCEL)
            sibling_still_owns_scope = root_scope is not None and any(
                scope == root_scope for scope in self._runs.values()
            )
            if not sibling_still_owns_scope:
                abort_scope = root_scope
        # Abort outside the scheduler lock: ``abort_scope`` drains node-complete
        # listeners that may deliver stream events (controller ``stream_lock``) or
        # call ``owns_table_stream`` (needs this lock). Holding ``_lock`` here ABBA /
        # self-deadlocks with ``reschedule_row`` (stream_lock -> cancel -> abort).
        if abort_scope is not None and abort_generation is not None:
            self._abort_orchestrator_scope(abort_scope, abort_generation)

    def _preempt_active_stream_locked(self: InferenceRowScheduler) -> None:
        """Clear global pause and drop the preempted stream's held submissions and binding."""
        preempted_token = self._scope_guard.active_table_stream_token
        # The guard preempts only an active stream, and an active stream always has a token.
        assert preempted_token is not None
        self._globally_paused = False
        self._release_stream_locked(preempted_token)

    def _reset_stream_state_locked(self: InferenceRowScheduler) -> None:
        """Clear global pause, every held submission and every stream binding."""
        self._globally_paused = False
        self._held_initial_submissions.clear()
        self._stream_bindings.clear()

    def _release_stream_locked(self: InferenceRowScheduler, stream_token: str) -> None:
        """Drop one stream's held submissions and its binding."""
        self._held_initial_submissions = [
            held for held in self._held_initial_submissions if held.stream_token != stream_token
        ]
        self._stream_bindings.pop(stream_token, None)

    def _invalidate_retained_state_locked(self: InferenceRowScheduler) -> None:
        """Drop all stream state and every run, for shutdown or a hard invalidate.

        Detaches every run without cancelling it, then clears every stream
        resolution and every retained RowRun shell.
        """
        from api.analytics.scores.tier_row_run_registry import clear_row_runs
        from api.streaming.table_stream.row_stream_resolution_registry import (
            clear_stream_resolutions,
        )

        self._reset_stream_state_locked()
        for run_id in list(self._runs):
            self._remove_run_locked(run_id, op=RowLifecycleOp.DETACH)
        clear_stream_resolutions()
        clear_row_runs()

    def _abort_orchestrator_scope(
        self: InferenceRowScheduler,
        root_scope: ComputeScope,
        execution_generation: int,
    ) -> None:
        """Fail in-flight orchestrator work for ``root_scope`` after a row-run cancel.

        Without this, a later ``force_fresh`` submit attaches to the still-running node
        and ``tier_solve`` fails with a missing RowRun after retire.

        Uses :class:`~api.compute.errors.ComputeScopeAbortedError` so dependents on the
        singleton DAG (e.g. fleet) stay ``waiting_deps`` instead of cascading the cancel
        into a user-visible fleet table error.

        Must run without the scheduler lock held (see ``cancel_run``). Always targets the
        process-wide singleton orchestrator (#209).
        """
        from api.compute.errors import ComputeScopeAbortedError
        from api.compute.runtime import get_compute_orchestrator

        get_compute_orchestrator().abort_scope(
            root_scope,
            ComputeScopeAbortedError(SCORES_ROW_RUN_CANCELLED_MESSAGE),
            expected_execution_generation=execution_generation,
        )

    def _remove_run_locked(
        self: InferenceRowScheduler,
        run_id: str,
        *,
        op: RowLifecycleOp = RowLifecycleOp.RETIRE,
    ) -> None:
        """Drop scheduler stream maps; apply scores row lifecycle for ``op``.

        Lifecycle (shell + admission + drain/token) is owned by
        :func:`api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`.
        This method owns only the scheduler plane (maps / held submissions).

        ``CANCEL`` applies lifecycle *before* map drop so late persist still
        DENYs. ``DETACH`` / ``RETIRE`` apply after map drop. Full invalidate
        also clears via :func:`clear_row_runs`.
        """
        from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle

        if op is RowLifecycleOp.CANCEL:
            # Admission + seal + token before dropping scheduler maps.
            apply_scores_row_lifecycle(op, run_id)
            self._pending_accepts.discard(run_id)

        root_scope = self._runs.pop(run_id, None)
        self._execution_generation_by_run_id.pop(run_id, None)
        if op is not RowLifecycleOp.CANCEL:
            apply_scores_row_lifecycle(op, run_id)
        # Keep stream-resolution state so a late peer binding cannot supersede an
        # already-resolved row after its live scheduler entry has gone away.
        if root_scope is None:
            return
        self._held_initial_submissions = [
            held for held in self._held_initial_submissions if held.root_scope != root_scope
        ]

    @staticmethod
    def _is_cancel_abort_failure(snapshot: ScopeLifecycleSnapshot) -> bool:
        if snapshot.state != "failed":
            return False
        from api.compute.errors import ComputeScopeAbortedError

        return isinstance(snapshot.error, ComputeScopeAbortedError)

    def _adapter_row_run(self: InferenceRowScheduler, run_id: str) -> RowRun | None:
        """Resolve RowRun from the single registry owner (any retained phase)."""
        from api.analytics.scores.tier_row_run_registry import get_row_run

        return get_row_run(run_id)
