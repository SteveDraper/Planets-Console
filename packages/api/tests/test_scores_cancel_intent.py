"""Contract tests for scores cancel intent (admission + delivery + token)."""

from __future__ import annotations

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.row_run import RowRun, RowRunPhase
from api.analytics.military_score_inference.row_stream_resolution import (
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)
from api.analytics.military_score_inference.row_stream_resolution_registry import (
    get_stream_resolution,
    reset_stream_resolution_registry_for_tests,
    transition_stream_resolution,
)
from api.analytics.scores.cancel_intent import apply_scores_row_cancel
from api.analytics.scores.persist_decision import PersistDecision, decide_scores_row_persist
from api.analytics.scores.tier_row_run_registry import (
    get_row_run,
    get_row_run_phase,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
)


def _session(sample_turn) -> InferenceRowStreamSession:
    score = sample_turn.scores[0]
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def test_apply_scores_row_cancel_is_one_command(sample_turn) -> None:
    reset_tier_row_run_registry_for_tests()
    reset_stream_resolution_registry_for_tests()
    try:
        run = RowRun(_session(sample_turn))
        register_row_run(run)
        assert not run.session.cancel_token.is_cancelled()

        apply_scores_row_cancel(
            run.run_id,
            mark_stream_canceled=lambda rid: transition_stream_resolution(
                rid,
                RowStreamResolutionTrigger.CANCELED,
            ),
        )

        assert get_row_run(run.run_id) is None
        assert get_row_run_phase(run.run_id) is RowRunPhase.CANCELLED
        assert decide_scores_row_persist(run.run_id) is PersistDecision.DENY_CANCEL
        assert run.session.cancel_token.is_cancelled()
        resolution = get_stream_resolution(run.run_id)
        assert resolution is not None
        assert resolution.state is RowStreamResolutionState.CANCELED
    finally:
        reset_tier_row_run_registry_for_tests()
        reset_stream_resolution_registry_for_tests()
