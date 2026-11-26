"""Execute one inference search tier job for a scheduled stream row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
    continue_ladder_state,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceSolution
from api.analytics.military_score_inference.policy_ladder import finalize_policy_ladder_result
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    fleet_torp_input_status_diagnostics,
)
from api.analytics.military_score_inference.row_complete_factory import (
    row_complete_from_ladder_finalize,
    row_complete_stopped,
    row_complete_with_summary,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.search_effort import stream_row_search_effort
from api.analytics.military_score_inference.tier_ladder import TierLadder
from api.models.game import TurnInfo


def stream_row_search_effort_allowance() -> float:
    """Row inference search effort allowance for one stream ladder."""
    return stream_row_search_effort()


@dataclass(frozen=True)
class TierJobContinue:
    """The row needs another tier job on its ladder (already advanced by the runner)."""


@dataclass(frozen=True)
class TierJobRowComplete:
    """The row's ladder finished with this terminal payload."""

    row_complete: RowComplete


# One tier job ends in exactly one of these; there is no empty outcome.
type TierJobOutcome = TierJobContinue | TierJobRowComplete


@dataclass(frozen=True)
class InferenceTierJobCallbacks:
    """Stream callbacks for one tier job.

    ``emit_held_solutions`` runs on every admitted solution; the scheduler
    decides whether the row's stream shows held solutions.
    """

    emit_tier_started_progress: Callable[[], None]
    emit_progress: Callable[[], None]
    emit_held_solutions: Callable[[], None]


def solve_context(run: RowRun) -> tuple[InferenceObservation, TurnInfo]:
    orchestration = run.ladder.orchestration
    if orchestration is not None:
        return orchestration.current_observation(), orchestration.current_solve_turn()
    return run.session.observation, run.session.turn


def _session_solve_context(run: RowRun) -> tuple[InferenceObservation, TurnInfo]:
    return run.session.observation, run.session.turn


def build_stopped_row_complete(run: RowRun) -> RowComplete:
    orchestration = run.ladder.orchestration
    state = run.ladder.ladder_state
    if orchestration is not None and orchestration.current_segment() is None:
        exhausted = orchestration.exhausted_segments_row_complete()
        if exhausted is not None:
            return row_complete_stopped(base=exhausted)
        observation, turn = _session_solve_context(run)
        return row_complete_stopped(ladder_state=state, observation=observation, turn=turn)
    observation, turn = solve_context(run)
    if orchestration is not None:
        return orchestration.build_stopped_row_complete(state, observation, turn)
    return row_complete_stopped(ladder_state=state, observation=observation, turn=turn)


def _outcome_when_accelerated_segments_exhausted(
    run: RowRun,
    orchestration: InferenceStreamOrchestration,
) -> TierJobRowComplete:
    """Idempotent terminal outcome for a duplicate/late tier after segments finish."""
    exhausted = orchestration.exhausted_segments_row_complete()
    if exhausted is not None:
        return TierJobRowComplete(row_complete=exhausted)
    observation, turn = _session_solve_context(run)
    return TierJobRowComplete(
        row_complete=row_complete_stopped(
            ladder_state=run.ladder.ladder_state,
            observation=observation,
            turn=turn,
        )
    )


def _outcome_after_ladder_complete(
    run: RowRun,
    orchestration: InferenceStreamOrchestration | None,
    state: PolicyLadderState,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> TierJobOutcome:
    if state.refused_result is not None:
        result, *_ = finalize_policy_ladder_result(state, observation, turn)
        return TierJobRowComplete(row_complete=row_complete_with_summary(result))

    if orchestration is not None:
        segment_row_complete = orchestration.finish_ladder_segment(state, observation, turn)
        if segment_row_complete is None:
            run.ladder = TierLadder(continue_ladder_state(state, run.session), orchestration)
            return TierJobContinue()
        return TierJobRowComplete(row_complete=segment_row_complete)

    result, catalog, problem, policy_steps_attempted, step_diagnostics = (
        finalize_policy_ladder_result(state, observation, turn)
    )
    return TierJobRowComplete(
        row_complete=row_complete_from_ladder_finalize(
            result,
            catalog,
            problem,
            policy_steps_attempted,
            step_diagnostics,
            observation=observation,
            turn=turn,
            extra_diagnostics=fleet_torp_input_status_diagnostics(
                run.session.fleet_torp_input_status,
            ),
            resolved_mask=state.resolved_mask,
        ),
    )


def run_inference_tier_job(
    run: RowRun,
    callbacks: InferenceTierJobCallbacks,
) -> TierJobOutcome:
    """Run one policy-ladder tier step and return the scheduler's next action.

    Holds ``run.tier_lock`` for the whole job so duplicate concurrent dispatches
    serialize on shared orchestration / ladder state. The runner is the only
    code that moves ``run.ladder`` on to the next accelerated segment, and
    it does so under that lock before returning :class:`TierJobContinue`. When
    accelerated segments are already exhausted, returns an idempotent terminal
    outcome instead of raising.
    """
    with run.tier_lock:
        return _run_inference_tier_job_locked(run, callbacks)


def _run_inference_tier_job_locked(
    run: RowRun,
    callbacks: InferenceTierJobCallbacks,
) -> TierJobOutcome:
    session = run.session
    if session.cancel_token.is_cancelled():
        return TierJobRowComplete(row_complete=build_stopped_row_complete(run))

    state = run.ladder.ladder_state
    orchestration = run.ladder.orchestration
    if orchestration is not None and orchestration.current_segment() is None:
        return _outcome_when_accelerated_segments_exhausted(run, orchestration)

    observation, turn = solve_context(run)

    def on_admitted(_solution: InferenceSolution) -> None:
        callbacks.emit_held_solutions()

    callbacks.emit_tier_started_progress()
    run_policy_ladder_tier_step(
        state,
        observation,
        turn,
        time_limit_seconds=None,
        search_effort_allowance=stream_row_search_effort_allowance(),
        cancel_token=session.cancel_token,
        on_admitted=on_admitted,
    )
    callbacks.emit_progress()

    if session.cancel_token.is_cancelled() or state.cancelled:
        return TierJobRowComplete(row_complete=build_stopped_row_complete(run))

    if not state.ladder_complete:
        return TierJobContinue()

    return _outcome_after_ladder_complete(run, orchestration, state, observation, turn)
