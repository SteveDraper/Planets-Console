"""Deliver scores DAG outcomes into one table-stream row lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

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
from api.analytics.military_score_inference.stream_terminal_policy import (
    StreamTerminalDispatch,
    TerminalSource,
    resolve_stream_terminal_dispatch,
)
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.scope import ComputeScope
from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_stream_resolution import (
    RowStreamDelivery,
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)
from api.streaming.table_stream.row_stream_resolution_registry import (
    get_stream_resolution,
    transition_stream_resolution,
)
from api.streaming.table_stream.terminal_route import TerminalRoute, route_terminal

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
    )
    from api.analytics.military_score_inference.inference_table_stream_controller import (
        InferenceTableStreamController,
    )


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
        """Deliver one stream-row terminal for a durable or orphan source.

        Returns True when admission or a domain terminal finished the row for this call.
        Orphan deliveries also finalize the matching row run; node-complete callers
        finalize themselves (sibling-active races).
        """
        resolved = session or self._open_stream_session_for_scope(scope)
        if resolved is None:
            return False
        if source is TerminalSource.ORPHAN and self._controller_for_compute_scope(scope) is None:
            return False

        resolved_event = event
        if resolved_event is None and snapshot is not None:
            resolved_event = self._row_complete_from_result_wire(snapshot.result_wire)

        dispatch = resolve_stream_terminal_dispatch(
            source=source,
            has_event=resolved_event is not None,
        )

        match dispatch:
            case StreamTerminalDispatch.EMIT_DURABLE | StreamTerminalDispatch.EMIT_DURABLE_FINALIZE:
                if resolved_event is None:
                    return False
                trigger = (
                    RowStreamResolutionTrigger.DURABLE_COMPLETE
                    if isinstance(resolved_event, RowComplete)
                    else RowStreamResolutionTrigger.DURABLE_FAILURE
                )
                return self._emit_domain_terminal(
                    resolved,
                    resolved_event,
                    trigger,
                    finalize=dispatch is StreamTerminalDispatch.EMIT_DURABLE_FINALIZE,
                )
            case StreamTerminalDispatch.ADMIT_FAIL:
                return self._admit_after_soft_provisional(scope, resolved)
            case StreamTerminalDispatch.ORPHAN_EMPTY:
                return self._deliver_orphan_empty(scope, resolved, snapshot)
        assert_never(dispatch)

    def _emit_domain_terminal(
        self: InferenceRowScheduler,
        session: InferenceRowStreamSession,
        event: RowComplete | RowFailed,
        trigger: RowStreamResolutionTrigger,
        *,
        finalize: bool,
    ) -> bool:
        with self._lock:
            delivery = self._transition_stream_resolution_locked(session.run_id, trigger)
        self._emit_stream_terminal(session, event, delivery)
        if finalize:
            self._finalize_row_run(session)
        return delivery is not RowStreamDelivery.SILENCE

    def _deliver_orphan_empty(
        self: InferenceRowScheduler,
        scope: ComputeScope,
        session: InferenceRowStreamSession,
        snapshot: ScopeLifecycleSnapshot | None,
    ) -> bool:
        with self._lock:
            resolution = get_stream_resolution(session.run_id)
            state = resolution.state if resolution is not None else RowStreamResolutionState.OPEN
        if state in {
            RowStreamResolutionState.HARD_TERMINAL,
            RowStreamResolutionState.CANCELED,
        }:
            return False
        if snapshot is not None and snapshot.state == "failed":
            detail = (
                str(snapshot.error) if snapshot.error is not None else "Inference tier solve failed"
            )
            delivered = self._emit_domain_terminal(
                session,
                RowFailed(detail=detail),
                RowStreamResolutionTrigger.DURABLE_FAILURE,
                finalize=True,
            )
            return delivered
        if self._admit_after_soft_provisional(scope, session):
            self._finalize_row_run(session)
            return True
        return False

    def _admit_after_soft_provisional(
        self: InferenceRowScheduler,
        scope: ComputeScope,
        session: InferenceRowStreamSession,
    ) -> bool:
        """Claim soft-provisional, then the admission wire, else fail the row."""
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

    def _emit_stream_terminal(
        self: InferenceRowScheduler,
        session: InferenceRowStreamSession,
        event: RowComplete | RowFailed,
        delivery: RowStreamDelivery,
    ) -> None:
        route = route_terminal(delivery, session.run_id)
        if route is TerminalRoute.SILENCE:
            return
        if route is TerminalRoute.PENDING:
            controller = self._controller_for_stream_session(session)
            if controller is not None:
                controller.push_domain_event_pending_wire(session, event)
            return
        deliver_inference_domain_event_to_open_stream(session, event)

    def _transition_stream_resolution_locked(
        self: InferenceRowScheduler,
        run_id: str,
        trigger: RowStreamResolutionTrigger,
    ) -> RowStreamDelivery:
        return transition_stream_resolution(run_id, trigger)

    def _controller_for_stream_session(
        self: InferenceRowScheduler,
        session: InferenceRowStreamSession,
    ) -> InferenceTableStreamController | None:
        from api.analytics.military_score_inference.inference_table_stream_registry import (
            controller_for_scope,
        )

        return controller_for_scope(InferenceStreamScope.from_session(session))

    def _controller_for_compute_scope(
        self: InferenceRowScheduler,
        scope: ComputeScope,
    ) -> InferenceTableStreamController | None:
        from api.analytics.military_score_inference.inference_table_stream_registry import (
            controller_for_scope,
        )

        return controller_for_scope(InferenceStreamScope.from_root(scope))

    def _open_stream_session_for_scope(
        self: InferenceRowScheduler,
        scope: ComputeScope,
    ) -> InferenceRowStreamSession | None:
        controller = self._controller_for_compute_scope(scope)
        if controller is None:
            return None
        scheduled = controller.scheduled_rows.get(scope.player_id)
        return scheduled.session if scheduled is not None else None

    def _reopen_stream_row_for_force_fresh(
        self: InferenceRowScheduler,
        scope: ComputeScope,
    ) -> None:
        session = self._open_stream_session_for_scope(scope)
        if session is None:
            return
        controller = self._controller_for_compute_scope(scope)
        if controller is None:
            return
        if not stream_drain.reopen_if_soft(session.run_id):
            return
        controller.wake_multiplex.set()
