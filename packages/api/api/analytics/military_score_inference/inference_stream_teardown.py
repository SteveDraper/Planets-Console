"""Stream detach / abort helpers for the scores inference row scheduler.

Owns begin_scope preempt detach, cancel_run abort, and turn-scoped stream
teardown without cancelling in-flight solve work on detach.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.analytics.military_score_inference.row_run import RowRun

# Shared abort detail so node-complete listeners can ignore intentional cancels
# (must not deliver RowFailed / orphan terminals to an open multiplex).
SCORES_ROW_RUN_CANCELLED_MESSAGE = "scores inference row run cancelled"


@dataclass
class InferenceStreamOrchestratorBinding:
    """One table-stream's leader context on the process-wide singleton orchestrator."""

    orchestrator: ComputeOrchestrator
    query_context: AnalyticQueryContext
    unregister_dispatch_gate: Callable[[], None] | None = None


@dataclass(frozen=True)
class HeldTierSubmission:
    stream_token: str
    root_scope: ComputeScope


class InferenceStreamTeardownMixin:
    """Detach stream ownership vs cancel+abort orchestrator scopes."""

    def begin_scope(self: InferenceRowScheduler, scope: InferenceStreamScope) -> str:
        """Claim the active table-stream scope, detaching the prior stream's row runs.

        Background ensure RowRuns for *other* turns must survive. Detaching them on
        ``begin_scope`` (e.g. opening the turn-8 stream while turn-3 background
        warm is in flight) left fleet waiting forever on aborted/missing scores
        deps. Only the prior active stream turn is detached; a first claim
        (no prior scope) leaves retained runs alone.

        Detach drops RowRun registrations and stream bindings but does **not**
        cancel solve tokens, set cancellation fences, or abort orchestrator
        nodes -- in-flight tier workers may still finish, persist from the
        RowComplete payload, and complete the DAG node. ``cancel_run`` is the
        explicit cancel intent (token + fence + abort).
        """
        with self._lock:
            prior = self._scope_guard.active_scope

            def on_same_scope_preempt() -> None:
                self._detach_stream_runs_locked(turn=scope.turn_number)

            def on_scope_change() -> None:
                if prior is None:
                    return
                self._detach_stream_runs_locked(turn=prior.turn_number)

            return self._scope_guard.begin_scope_locked(
                scope,
                on_same_scope_preempt=on_same_scope_preempt,
                on_scope_change=on_scope_change,
            )

    def cancel_run(self: InferenceRowScheduler, run_id: str) -> None:
        """Cancel one row run and abort its orchestrator scope.

        Unlike ``_detach_stream_runs_locked`` (stream switch / begin_scope), which
        only drops stream ownership without cancelling solve work, cancel cancels
        the RowRun token, sets a cancellation fence (survives unregister so
        ``ScoresPersistencePolicy`` refuses late persist), and aborts in-flight
        orchestrator nodes so a later ``force_fresh`` submit cannot attach to a
        still-running node with a missing RowRun.
        """
        from api.analytics.scores.tier_row_run_registry import mark_row_run_cancelled

        abort_scope: ComputeScope | None = None
        abort_generation: int | None = None
        with self._lock:
            row_run = self._adapter_row_run(run_id)
            root_scope = self._runs.get(run_id)
            from api.analytics.military_score_inference.row_stream_resolution import (
                RowStreamResolutionTrigger,
            )

            self._transition_stream_resolution_locked(
                run_id,
                RowStreamResolutionTrigger.CANCELED,
            )
            # Use the generation cached at submit/wake -- never call into the
            # orchestrator while holding the scheduler lock (ABBA with orch drain
            # paths that take this lock, and with diagnostics snapshot on orch).
            abort_generation = self._execution_generation_by_run_id.get(run_id)
            if row_run is not None:
                row_run.session.cancel_token.cancel()
            # Fence before unregister: persist must not race on missing RowRun.
            mark_row_run_cancelled(run_id)
            self._remove_run_locked(run_id)
            abort_scope = root_scope
        # Abort outside the scheduler lock: ``abort_scope`` drains node-complete
        # listeners that may deliver stream events (controller ``stream_lock``) or
        # call ``owns_table_stream`` (needs this lock). Holding ``_lock`` here ABBA /
        # self-deadlocks with ``reschedule_row`` (stream_lock -> cancel -> abort).
        if abort_scope is not None and abort_generation is not None:
            self._abort_orchestrator_scope(abort_scope, abort_generation)

    def _detach_stream_runs_locked(
        self: InferenceRowScheduler,
        *,
        turn: int | None = None,
    ) -> None:
        """Detach stream ownership for one turn without cancelling solve work.

        Used by ``begin_scope`` when switching table streams. Unregisters RowRuns
        and drops stream bindings for ``turn`` only; other turns are untouched.
        Does **not** cancel RowRun tokens, set cancellation fences, or call
        ``abort_scope`` -- in-flight tier workers may still finish, persist from
        the RowComplete payload, and complete the DAG node. ``cancel_run`` is the
        explicit cancel intent (token + fence + abort).

        ``_stream_resolutions`` is left untouched for a turn-scoped detach:
        ``_remove_run_locked`` already keeps each detached run's resolution so a
        late peer binding cannot supersede an already-resolved row, and other-turn
        resolutions must survive a preempt. A full invalidate (``turn is None``,
        e.g. shutdown) clears every resolution along with everything else.
        """
        self._globally_paused = False
        if turn is None:
            self._held_initial_submissions.clear()
        else:
            self._held_initial_submissions = [
                held for held in self._held_initial_submissions if held.root_scope.turn != turn
            ]
        for run_id in list(self._runs):
            root_scope = self._runs.get(run_id)
            if turn is not None and root_scope is not None and root_scope.turn != turn:
                continue
            self._remove_run_locked(run_id)
        if turn is None:
            self._stream_resolutions.clear()
        for stream_token in list(self._stream_bindings):
            binding = self._stream_bindings.pop(stream_token)
            self._release_stream_binding_locked(binding)

    def _invalidate_retained_state_locked(self: InferenceRowScheduler) -> None:
        # Full detach for shutdown / hard invalidate -- not used by begin_scope.
        self._detach_stream_runs_locked(turn=None)

    def _abort_orchestrator_scope(
        self: InferenceRowScheduler,
        root_scope: ComputeScope,
        execution_generation: int,
    ) -> None:
        """Fail in-flight orchestrator work for ``root_scope`` after a row-run cancel.

        Without this, a later ``force_fresh`` submit attaches to the still-running node
        and ``tier_solve`` fails with a missing RowRun after unregister.

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

    def _release_stream_binding_locked(
        self: InferenceRowScheduler,
        binding: InferenceStreamOrchestratorBinding,
    ) -> None:
        if binding.unregister_dispatch_gate is not None:
            binding.unregister_dispatch_gate()
            binding.unregister_dispatch_gate = None

    def _remove_run_locked(self: InferenceRowScheduler, run_id: str) -> None:
        from api.analytics.scores.tier_row_run_registry import unregister_row_run

        root_scope = self._runs.pop(run_id, None)
        self._execution_generation_by_run_id.pop(run_id, None)
        unregister_row_run(run_id)
        # Keep resolution state so a late peer binding cannot supersede an already
        # resolved row after its RowRun registration has gone away.
        if root_scope is None:
            return
        self._held_initial_submissions = [
            held for held in self._held_initial_submissions if held.root_scope != root_scope
        ]

    @staticmethod
    def _is_cancel_abort_failure(node: object) -> bool:
        if getattr(node, "state", None) != "failed":
            return False
        from api.compute.errors import ComputeScopeAbortedError

        return isinstance(getattr(node, "error", None), ComputeScopeAbortedError)

    @staticmethod
    def _adapter_row_run(run_id: str) -> RowRun | None:
        from api.analytics.scores.tier_row_run_registry import get_row_run

        return get_row_run(run_id)
