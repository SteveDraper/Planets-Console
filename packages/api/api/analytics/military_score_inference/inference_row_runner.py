"""Execute one inference search tier job for a scheduled stream row."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.military_score_inference.actions import DEFAULT_INFERENCE_TIME_LIMIT_SECONDS

from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.models import InferenceObservation, InferenceSolution
from api.analytics.military_score_inference.policy_ladder import finalize_policy_ladder_result
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.row_complete_factory import (
    row_complete_from_ladder_finalize,
    row_complete_stopped,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.models.game import TurnInfo


def stream_tier_time_limit_seconds() -> float:
    """Per-tier CP-SAT budget for SPA streaming (one policy step per scheduler job)."""
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_STREAM_TIER_TIME_LIMIT_SECONDS")
    if raw is not None:
        return float(raw)
    return DEFAULT_INFERENCE_TIME_LIMIT_SECONDS


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


def solve_context(run: RowRun) -> tuple[InferenceObservation, TurnInfo]:
    orchestration = run.orchestration
    if orchestration is not None:
        return orchestration.current_observation(), orchestration.current_solve_turn()
    return run.session.observation, run.session.turn


def build_stopped_row_complete(run: RowRun) -> RowComplete:
    orchestration = run.orchestration
    state = run.ladder_state
    observation, turn = solve_context(run)
    if orchestration is not None:
        return orchestration.build_stopped_row_complete(state, observation, turn)
    return row_complete_stopped(ladder_state=state, observation=observation, turn=turn)


def _outcome_after_ladder_complete(
    run: RowRun,
    state: PolicyLadderState,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> TierJobOutcome:
    orchestration = run.orchestration
    if orchestration is not None:
        advance = orchestration.finish_ladder_segment(state, observation, turn)
        if advance.continue_next_segment:
            return TierJobOutcome(
                enqueue_continuation=True,
                next_ladder_state=orchestration.new_ladder_state(
                    resolved_mask=run.session.resolved_mask,
                ),
            )
        if advance.row_complete is not None:
            return TierJobOutcome(row_complete=advance.row_complete)
        return TierJobOutcome()

    result, catalog, problem, policy_steps_attempted, step_diagnostics = (
        finalize_policy_ladder_result(state, observation, turn)
    )
    return TierJobOutcome(
        row_complete=row_complete_from_ladder_finalize(
            result,
            catalog,
            problem,
            policy_steps_attempted,
            step_diagnostics,
            observation=observation,
            turn=turn,
        ),
    )


def run_inference_tier_job(
    run: RowRun,
    callbacks: InferenceTierJobCallbacks,
) -> TierJobOutcome:
    """Run one policy-ladder tier step and return the scheduler's next action."""
    session = run.session
    if session.cancel_token.is_cancelled():
        return TierJobOutcome(row_complete=build_stopped_row_complete(run))

    state = run.ladder_state
    if state is None:
        return TierJobOutcome()

    observation, turn = solve_context(run)
    orchestration = run.orchestration

    def on_admitted(_solution: InferenceSolution) -> None:
        if orchestration is None or orchestration.should_emit_streaming_solutions():
            callbacks.emit_held_solutions(observation)

    callbacks.emit_tier_started_progress()
    run_policy_ladder_tier_step(
        state,
        observation,
        turn,
        time_limit_seconds=stream_tier_time_limit_seconds(),
        cancel_token=session.cancel_token,
        on_admitted=on_admitted,
    )
    callbacks.emit_progress()

    if session.cancel_token.is_cancelled() or state.cancelled:
        return TierJobOutcome(row_complete=build_stopped_row_complete(run))

    if not state.ladder_complete:
        return TierJobOutcome(enqueue_continuation=True)

    return _outcome_after_ladder_complete(run, state, observation, turn)
