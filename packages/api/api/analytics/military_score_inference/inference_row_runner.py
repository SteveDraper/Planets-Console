"""Execute one inference search tier job for a scheduled stream row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
    build_policy_ladder_stopped_row_complete,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceSolution
from api.analytics.military_score_inference.policy_ladder import (
    PolicyLadderState,
    finalize_policy_ladder_result,
    run_policy_ladder_tier_step,
)
from api.models.game import TurnInfo


@dataclass(frozen=True)
class TierJobOutcome:
    """Scheduler action after one tier job finishes."""

    enqueue_continuation: bool = False
    next_ladder_state: PolicyLadderState | None = None
    row_complete: RowComplete | None = None


@dataclass(frozen=True)
class InferenceTierJobCallbacks:
    emit_tier_started_progress: Callable[[], None]
    emit_progress: Callable[[], None]
    emit_held_solutions: Callable[[InferenceObservation], None]


def solve_context(session: InferenceRowStreamSession) -> tuple[InferenceObservation, TurnInfo]:
    orchestration = session.orchestration
    if orchestration is not None:
        return orchestration.current_observation(), orchestration.current_solve_turn()
    return session.observation, session.turn


def should_emit_streaming_solutions(
    orchestration: InferenceStreamOrchestration | None,
) -> bool:
    if orchestration is None:
        return True
    return orchestration.should_emit_streaming_solutions()


def build_stopped_row_complete(session: InferenceRowStreamSession) -> RowComplete:
    orchestration = session.orchestration
    state = session.ladder_state
    observation, turn = solve_context(session)
    if orchestration is not None:
        return orchestration.build_stopped_row_complete(state, observation, turn)
    return build_policy_ladder_stopped_row_complete(state, observation, turn)


def _finalize_policy_ladder_row_complete(
    session: InferenceRowStreamSession,
    state: PolicyLadderState,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> RowComplete:
    result, catalog, problem, policy_steps_attempted, step_diagnostics = (
        finalize_policy_ladder_result(
            state,
            observation,
            turn,
        )
    )
    return RowComplete(
        result=result,
        catalog=catalog,
        problem=problem,
        policy_steps_attempted=policy_steps_attempted,
        step_diagnostics=step_diagnostics,
    )


def _outcome_after_ladder_complete(
    session: InferenceRowStreamSession,
    state: PolicyLadderState,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> TierJobOutcome:
    orchestration = session.orchestration
    if orchestration is not None:
        advance = orchestration.finish_ladder_segment(state, observation, turn)
        if advance.continue_next_segment:
            return TierJobOutcome(
                enqueue_continuation=True,
                next_ladder_state=orchestration.new_ladder_state(),
            )
        if advance.row_complete is not None:
            return TierJobOutcome(row_complete=advance.row_complete)
        return TierJobOutcome()

    return TierJobOutcome(
        row_complete=_finalize_policy_ladder_row_complete(session, state, observation, turn),
    )


def run_inference_tier_job(
    session: InferenceRowStreamSession,
    callbacks: InferenceTierJobCallbacks,
) -> TierJobOutcome:
    """Run one policy-ladder tier step and return the scheduler's next action."""
    if session.cancel_token.is_cancelled():
        return TierJobOutcome(row_complete=build_stopped_row_complete(session))

    state = session.ladder_state
    if state is None:
        return TierJobOutcome()

    observation, turn = solve_context(session)
    orchestration = session.orchestration

    def on_admitted(_solution: InferenceSolution) -> None:
        if should_emit_streaming_solutions(orchestration):
            callbacks.emit_held_solutions(observation)

    callbacks.emit_tier_started_progress()
    run_policy_ladder_tier_step(
        state,
        observation,
        turn,
        time_limit_seconds=None,
        cancel_token=session.cancel_token,
        on_admitted=on_admitted,
    )
    callbacks.emit_progress()

    if session.cancel_token.is_cancelled() or state.cancelled:
        return TierJobOutcome(row_complete=build_stopped_row_complete(session))

    if not state.ladder_complete:
        return TierJobOutcome(enqueue_continuation=True)

    return _outcome_after_ladder_complete(session, state, observation, turn)
