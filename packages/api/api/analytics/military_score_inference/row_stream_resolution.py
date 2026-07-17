"""State transitions for resolving one inference row on a table stream."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

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
from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
    )
    from api.analytics.military_score_inference.inference_table_stream_controller import (
        InferenceTableStreamController,
    )


class RowStreamResolutionState(StrEnum):
    """The terminal-delivery state of one stream row."""

    OPEN = "open"
    SOFT_PROVISIONAL = "soft_provisional"
    HARD_TERMINAL = "hard_terminal"
    CANCELED = "canceled"


class RowStreamResolutionTrigger(StrEnum):
    """A scheduler event that can resolve a stream row."""

    SOFT_PROVISIONAL = "soft_provisional"
    DURABLE_COMPLETE = "durable_complete"
    DURABLE_FAILURE = "durable_failure"
    ADMISSION_MISSED = "admission_missed"
    CANCELED = "canceled"


class RowStreamDelivery(StrEnum):
    """How the caller must deliver the event selected by a transition."""

    DELIVER = "deliver"
    UPGRADE = "upgrade"
    SILENCE = "silence"


@dataclass
class RowStreamResolution:
    """Reduce stream terminal events into one explicit per-row lifecycle.

    Soft terminals are provisional: a later durable completion upgrades them through
    the pending wire. Hard terminals and cancellations silence all later events.
    """

    state: RowStreamResolutionState = RowStreamResolutionState.OPEN

    def transition(self, trigger: RowStreamResolutionTrigger) -> RowStreamDelivery:
        """Apply one trigger and return whether its event reaches the stream."""
        match self.state, trigger:
            case RowStreamResolutionState.OPEN, RowStreamResolutionTrigger.SOFT_PROVISIONAL:
                self.state = RowStreamResolutionState.SOFT_PROVISIONAL
                return RowStreamDelivery.DELIVER
            case (
                RowStreamResolutionState.SOFT_PROVISIONAL,
                RowStreamResolutionTrigger.DURABLE_COMPLETE,
            ):
                self.state = RowStreamResolutionState.HARD_TERMINAL
                return RowStreamDelivery.UPGRADE
            case (
                RowStreamResolutionState.OPEN,
                RowStreamResolutionTrigger.DURABLE_COMPLETE
                | RowStreamResolutionTrigger.DURABLE_FAILURE
                | RowStreamResolutionTrigger.ADMISSION_MISSED,
            ):
                self.state = RowStreamResolutionState.HARD_TERMINAL
                return RowStreamDelivery.DELIVER
            case (
                RowStreamResolutionState.SOFT_PROVISIONAL,
                RowStreamResolutionTrigger.ADMISSION_MISSED
                | RowStreamResolutionTrigger.DURABLE_FAILURE,
            ):
                self.state = RowStreamResolutionState.HARD_TERMINAL
                return RowStreamDelivery.DELIVER
            case _, RowStreamResolutionTrigger.CANCELED:
                self.state = RowStreamResolutionState.CANCELED
                return RowStreamDelivery.SILENCE
            case (
                RowStreamResolutionState.HARD_TERMINAL | RowStreamResolutionState.CANCELED,
                _,
            ):
                # Already resolved; every later trigger is a silenced no-op.
                return RowStreamDelivery.SILENCE
            case (
                RowStreamResolutionState.SOFT_PROVISIONAL,
                RowStreamResolutionTrigger.SOFT_PROVISIONAL,
            ):
                # Duplicate soft-provisional signal; the first one already delivered.
                return RowStreamDelivery.SILENCE
            case _:
                # Unreachable: every (state, trigger) pair is enumerated above.
                return RowStreamDelivery.SILENCE


class InferenceStreamResolutionMixin:
    """Resolve scores DAG outcomes into one table-stream row lifecycle."""

    def _deliver_soft_park_stream_terminal_if_needed(
        self: InferenceRowScheduler,
        scope: ComputeScope,
        node: object,
    ) -> None:
        session = self._open_stream_session_for_scope(scope)
        if session is None:
            return

        row_complete = self._row_complete_from_result_wire(getattr(node, "result_wire", None))
        if row_complete is not None:
            with self._lock:
                delivery = self._transition_stream_resolution_locked(
                    session.run_id,
                    RowStreamResolutionTrigger.SOFT_PROVISIONAL,
                )
            self._emit_stream_terminal(session, row_complete, delivery)
            return

        with self._lock:
            has_matching_run = any(
                root_scope.player_id == scope.player_id
                and root_scope.game_id == scope.game_id
                and root_scope.perspective == scope.perspective
                and scope.turn == root_scope.turn
                for root_scope in self._runs.values()
            )
        if not has_matching_run:
            return

        with self._lock:
            delivery = self._transition_stream_resolution_locked(
                session.run_id,
                RowStreamResolutionTrigger.SOFT_PROVISIONAL,
            )
        if delivery is RowStreamDelivery.SILENCE:
            return
        controller = self._controller_for_compute_scope(scope)
        if controller is not None and controller.push_admission_wire_terminal(session):
            return
        with self._lock:
            self._stream_resolutions.pop(session.run_id, None)

    def _deliver_stream_terminal(
        self: InferenceRowScheduler,
        session: InferenceRowStreamSession,
        event: RowComplete | RowFailed,
    ) -> None:
        with self._lock:
            delivery = self._transition_stream_resolution_locked(
                session.run_id,
                (
                    RowStreamResolutionTrigger.DURABLE_COMPLETE
                    if isinstance(event, RowComplete)
                    else RowStreamResolutionTrigger.DURABLE_FAILURE
                ),
            )
        self._emit_stream_terminal(session, event, delivery)

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

    def _deliver_empty_complete_terminal(
        self: InferenceRowScheduler,
        scope: ComputeScope,
        session: InferenceRowStreamSession,
    ) -> bool:
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

    def _deliver_orphan_stream_terminal_if_needed(
        self: InferenceRowScheduler,
        scope: ComputeScope,
        node: object,
    ) -> None:
        session = self._open_stream_session_for_scope(scope)
        if session is None:
            return
        if self._controller_for_compute_scope(scope) is None:
            return

        row_complete = self._row_complete_from_result_wire(getattr(node, "result_wire", None))
        if row_complete is not None:
            self._deliver_stream_terminal(session, row_complete)
            self._finalize_row_run(session)
            return

        with self._lock:
            state = self._stream_resolutions.get(session.run_id, RowStreamResolution()).state
        if state in {
            RowStreamResolutionState.HARD_TERMINAL,
            RowStreamResolutionState.CANCELED,
        }:
            return

        if getattr(node, "state", None) == "failed":
            detail = (
                str(node.error)
                if getattr(node, "error", None) is not None
                else "Inference tier solve failed"
            )
            self._deliver_stream_terminal(session, RowFailed(detail=detail))
            self._finalize_row_run(session)
            return

        if self._deliver_empty_complete_terminal(scope, session):
            self._finalize_row_run(session)

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
