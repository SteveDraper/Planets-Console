"""Deliver scores DAG outcomes into one table-stream row lifecycle."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from api.analytics.military_score_inference.inference_stream_domain_events import (
    RowComplete,
    RowFailed,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    deliver_inference_domain_event_to_open_stream,
)
from api.analytics.military_score_inference.row_stream_resolution import (
    RowStreamDelivery,
    RowStreamResolution,
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
    )
    from api.analytics.military_score_inference.inference_table_stream_controller import (
        InferenceTableStreamController,
    )


class TerminalSource(StrEnum):
    """Who is asking to close (or soft-close) the stream row."""

    PARKED = "parked"
    NODE_COMPLETE = "node_complete"
    ORPHAN = "orphan"


class InferenceStreamResolutionMixin:
    """Resolve scores DAG outcomes into one table-stream row lifecycle."""

    def _deliver_row_terminal(
        self: InferenceRowScheduler,
        *,
        source: TerminalSource,
        scope: ComputeScope,
        snapshot: ScopeLifecycleSnapshot | None = None,
        session: InferenceRowStreamSession | None = None,
        event: RowComplete | RowFailed | None = None,
    ) -> bool:
        """Deliver one stream-row terminal for park / durable / orphan sources.

        Returns True when admission or a domain terminal finished the row for this call.
        Orphan deliveries also finalize the matching row run; node-complete callers
        finalize themselves (sibling-active races). Soft park never finalizes.
        """
        resolved = session or self._open_stream_session_for_scope(scope)
        if resolved is None:
            return False
        if source is TerminalSource.ORPHAN and self._controller_for_compute_scope(scope) is None:
            return False

        resolved_event = event
        if resolved_event is None and snapshot is not None:
            resolved_event = self._row_complete_from_result_wire(snapshot.result_wire)

        if resolved_event is not None:
            trigger = (
                RowStreamResolutionTrigger.SOFT_PROVISIONAL
                if source is TerminalSource.PARKED
                else (
                    RowStreamResolutionTrigger.DURABLE_COMPLETE
                    if isinstance(resolved_event, RowComplete)
                    else RowStreamResolutionTrigger.DURABLE_FAILURE
                )
            )
            with self._lock:
                delivery = self._transition_stream_resolution_locked(resolved.run_id, trigger)
            self._emit_stream_terminal(resolved, resolved_event, delivery)
            if source is TerminalSource.ORPHAN:
                self._finalize_row_run(resolved)
            return delivery is not RowStreamDelivery.SILENCE

        if source is TerminalSource.PARKED:
            if not self._scope_has_matching_scheduler_run(scope):
                return False
            return self._admit_after_soft_provisional(scope, resolved, on_miss="revert")

        if source is TerminalSource.ORPHAN:
            with self._lock:
                state = self._stream_resolutions.get(
                    resolved.run_id, RowStreamResolution()
                ).state
            if state in {
                RowStreamResolutionState.HARD_TERMINAL,
                RowStreamResolutionState.CANCELED,
            }:
                return False
            if snapshot is not None and snapshot.state == "failed":
                detail = (
                    str(snapshot.error)
                    if snapshot.error is not None
                    else "Inference tier solve failed"
                )
                with self._lock:
                    delivery = self._transition_stream_resolution_locked(
                        resolved.run_id,
                        RowStreamResolutionTrigger.DURABLE_FAILURE,
                    )
                self._emit_stream_terminal(resolved, RowFailed(detail=detail), delivery)
                self._finalize_row_run(resolved)
                return True
            if self._admit_after_soft_provisional(scope, resolved, on_miss="fail"):
                self._finalize_row_run(resolved)
                return True
            return False

        # NODE_COMPLETE empty: admission before RowFailed (orphan parity).
        return self._admit_after_soft_provisional(scope, resolved, on_miss="fail")

    def _admit_after_soft_provisional(
        self: InferenceRowScheduler,
        scope: ComputeScope,
        session: InferenceRowStreamSession,
        *,
        on_miss: Literal["revert", "fail"],
    ) -> bool:
        """Claim soft-provisional, then admission wire or source-specific miss handling."""
        with self._lock:
            delivery = self._transition_stream_resolution_locked(
                session.run_id,
                RowStreamResolutionTrigger.SOFT_PROVISIONAL,
            )
        if delivery is RowStreamDelivery.SILENCE:
            return False
        controller = self._controller_for_compute_scope(scope)
        if controller is not None and controller.push_admission_wire_terminal(session):
            return True
        if on_miss == "revert":
            # Empty soft park: drop the provisional claim so wake can rebuild.
            with self._lock:
                self._stream_resolutions.pop(session.run_id, None)
            return False
        with self._lock:
            delivery = self._transition_stream_resolution_locked(
                session.run_id,
                RowStreamResolutionTrigger.ADMISSION_MISSED,
            )
        self._emit_stream_terminal(
            session,
            RowFailed(detail="Inference tier solve completed without row payload"),
            delivery,
        )
        return True

    def _scope_has_matching_scheduler_run(
        self: InferenceRowScheduler,
        scope: ComputeScope,
    ) -> bool:
        with self._lock:
            return any(
                root_scope.player_id == scope.player_id
                and root_scope.game_id == scope.game_id
                and root_scope.perspective == scope.perspective
                and scope.turn == root_scope.turn
                for root_scope in self._runs.values()
            )

    def _emit_stream_terminal(
        self: InferenceRowScheduler,
        session: InferenceRowStreamSession,
        event: RowComplete | RowFailed,
        delivery: RowStreamDelivery,
    ) -> None:
        if delivery is RowStreamDelivery.SILENCE:
            return
        controller = self._controller_for_stream_session(session)
        if delivery is RowStreamDelivery.UPGRADE or (
            controller is not None and session.run_id in controller.finished_run_ids
        ):
            if controller is not None:
                controller.push_domain_event_pending_wire(session, event)
                return
        deliver_inference_domain_event_to_open_stream(session, event)

    def _transition_stream_resolution_locked(
        self: InferenceRowScheduler,
        run_id: str,
        trigger: RowStreamResolutionTrigger,
    ) -> RowStreamDelivery:
        resolution = self._stream_resolutions.setdefault(run_id, RowStreamResolution())
        return resolution.transition(trigger)

    def _controller_for_stream_session(
        self: InferenceRowScheduler,
        session: InferenceRowStreamSession,
    ) -> InferenceTableStreamController | None:
        from api.analytics.military_score_inference.inference_table_stream_registry import (
            controller_for_scope,
        )

        return controller_for_scope(
            InferenceStreamScope(
                game_id=session.game_id,
                perspective=session.perspective,
                turn_number=session.turn_number,
            )
        )

    def _controller_for_compute_scope(
        self: InferenceRowScheduler,
        scope: ComputeScope,
    ) -> InferenceTableStreamController | None:
        from api.analytics.military_score_inference.inference_table_stream_registry import (
            controller_for_scope,
        )

        player_id = scope.player_id
        turn_number = scope.turn
        if not isinstance(player_id, int) or not isinstance(turn_number, int):
            return None
        return controller_for_scope(
            InferenceStreamScope(
                game_id=scope.game_id,
                perspective=scope.perspective,
                turn_number=turn_number,
            )
        )

    def _open_stream_session_for_scope(
        self: InferenceRowScheduler,
        scope: ComputeScope,
    ) -> InferenceRowStreamSession | None:
        controller = self._controller_for_compute_scope(scope)
        if controller is None:
            return None
        player_id = scope.player_id
        if not isinstance(player_id, int):
            return None
        scheduled = controller.scheduled_rows.get(player_id)
        return scheduled.session if scheduled is not None else None

    def _reopen_stream_row_for_force_fresh(
        self: InferenceRowScheduler,
        scope: ComputeScope,
    ) -> None:
        session = self._open_stream_session_for_scope(scope)
        if session is None:
            return
        with self._lock:
            resolution = self._stream_resolutions.get(session.run_id)
            if (
                resolution is None
                or resolution.state is not RowStreamResolutionState.SOFT_PROVISIONAL
            ):
                return
        controller = self._controller_for_compute_scope(scope)
        if controller is None:
            return
        with controller.stream_lock:
            controller.finished_run_ids.discard(session.run_id)
        controller.wake_multiplex.set()
