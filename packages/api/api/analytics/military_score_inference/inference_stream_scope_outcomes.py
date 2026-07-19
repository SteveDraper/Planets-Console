"""Map orchestrator scope outcomes onto scores inference row-run / stream terminals.

Owns the scores ``register_scope_outcome_listener`` decision tree: cancel-abort
ignore, soft park, peer-binding races, empty-complete, orphan fallback, and
row-run finalize. Stream terminal *delivery* stays in
``inference_stream_resolution``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.military_score_inference.inference_stream_domain_events import (
    RowFailed,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.soft_stream_policy import TerminalSource
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
    )


class InferenceStreamScopeOutcomesMixin:
    """Scores DAG scope-outcome listener: decide park / complete / fail / orphan."""

    def _on_orchestrator_scope_outcome(
        self: InferenceRowScheduler,
        snapshot: ScopeLifecycleSnapshot,
    ) -> None:
        scope = snapshot.scope
        if not _is_scores_player_turn_scope(scope):
            return
        # Intentional row-run cancel aborts in-flight DAG nodes. Do not fail (or
        # orphan-complete) the open multiplex -- reschedule will admit a replacement.
        if self._is_cancel_abort_failure(snapshot):
            return

        # Soft park: reattach empty/non-durable stream delivery without completing
        # the scores node (fleet ENSURE stays blocked until durable close).
        if snapshot.state == "parked":
            self._deliver_row_terminal(
                source=TerminalSource.PARKED,
                scope=scope,
                snapshot=snapshot,
            )
            return

        self._apply_scope_outcome_to_matching_runs(snapshot)
        self._deliver_orphan_terminal_if_needed(snapshot)

    def _apply_scope_outcome_to_matching_runs(
        self: InferenceRowScheduler,
        snapshot: ScopeLifecycleSnapshot,
    ) -> None:
        scope = snapshot.scope
        wire_run_id = self._run_id_from_result_wire(snapshot.result_wire)
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
            self._apply_scope_outcome_to_run(
                snapshot,
                run_id=run_id,
                sibling_still_active=sibling_still_active,
            )

    def _apply_scope_outcome_to_run(
        self: InferenceRowScheduler,
        snapshot: ScopeLifecycleSnapshot,
        *,
        run_id: str,
        sibling_still_active: bool,
    ) -> None:
        scope = snapshot.scope
        row_run = self._adapter_row_run(run_id)
        if row_run is None:
            # Stale scheduler entry (registry already dropped). Remove it so the
            # ensure-terminal fallback below can finish an open multiplex row.
            with self._lock:
                self._remove_run_locked(run_id)
            return

        session = row_run.session
        deliver_session = self._open_stream_session_for_scope(scope) or session

        if snapshot.state == "failed":
            if sibling_still_active:
                # Peer binding (e.g. stream_attached) still owns the shared RowRun.
                # Do not fail the stream or unregister -- the peer may still succeed.
                return
            detail = (
                str(snapshot.error) if snapshot.error is not None else "Inference tier solve failed"
            )
            self._deliver_row_terminal(
                source=TerminalSource.NODE_COMPLETE,
                scope=scope,
                session=deliver_session,
                event=RowFailed(detail=detail),
            )
            self._finalize_row_run(session)
            return

        if snapshot.state != "complete":
            return

        row_complete = self._row_complete_from_result_wire(snapshot.result_wire)
        if row_complete is None:
            if sibling_still_active:
                return
            # Parity with orphan empty-complete: admission before RowFailed.
            self._deliver_row_terminal(
                source=TerminalSource.NODE_COMPLETE,
                scope=scope,
                session=deliver_session,
            )
            self._finalize_row_run(session)
            return

        # Always attempt delivery: RowComplete may upgrade a prior empty/admission
        # terminal for the same stream session after force_fresh re-solve.
        self._deliver_row_terminal(
            source=TerminalSource.NODE_COMPLETE,
            scope=scope,
            session=deliver_session,
            event=row_complete,
        )
        if sibling_still_active:
            # Keep the process-wide RowRun registered until the last binding
            # for this scope reaches a terminal state (background + stream share it).
            return
        self._finalize_row_run(session)

    def _deliver_orphan_terminal_if_needed(
        self: InferenceRowScheduler,
        snapshot: ScopeLifecycleSnapshot,
    ) -> None:
        # Always re-check after matching-run handling. Empty / idempotent tier_solve can
        # leave the DAG terminal while multiplex still waits (stale ``_runs``, cancelled
        # session skip, or peer unregister). Do not rely on matching_run_ids alone.
        scope = snapshot.scope
        if snapshot.state in {"complete", "failed"} and not (
            self._scope_has_live_nonterminal_work(scope)
        ):
            self._deliver_row_terminal(
                source=TerminalSource.ORPHAN,
                scope=scope,
                snapshot=snapshot,
            )

    def _finalize_row_run(self: InferenceRowScheduler, session: InferenceRowStreamSession) -> None:
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
        """True when the singleton orchestrator still has non-terminal work for scope.

        Background warm and stream_attached bindings share the singleton orchestrator's
        one DAG per scope; a still-running node means a sibling submission is in flight.
        """
        from api.compute.runtime import get_compute_orchestrator

        node = get_compute_orchestrator().nodes.get(scope)
        return node is not None and node.state not in {"complete", "failed"}


def _is_scores_player_turn_scope(scope: ComputeScope) -> bool:
    if scope.analytic_id != SCORES_ANALYTIC_ID:
        return False
    if scope.turn == "*" or not isinstance(scope.turn, int):
        return False
    if scope.player_id == "*" or not isinstance(scope.player_id, int):
        return False
    return True
