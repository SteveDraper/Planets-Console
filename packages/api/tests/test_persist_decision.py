"""Unit tests for scores PersistDecision gate."""

from __future__ import annotations

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.row_run import RowRun, RowRunPhase
from api.analytics.scores.persist_decision import PersistDecision, decide_scores_row_persist
from api.analytics.scores.tier_row_run_registry import (
    detach_row_run,
    get_row_run_phase,
    mark_row_run_cancelled,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
    retire_row_run,
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


def test_persist_decision_table(sample_turn) -> None:
    reset_tier_row_run_registry_for_tests()
    try:
        run = RowRun(_session(sample_turn))
        register_row_run(run)
        assert get_row_run_phase(run.run_id) is RowRunPhase.REGISTERED
        assert decide_scores_row_persist(run.run_id) is PersistDecision.ALLOW

        run.session.cancel_token.cancel()
        assert decide_scores_row_persist(run.run_id) is PersistDecision.DENY_CANCEL

        # Fresh run for phase CANCELLED (token alone is already DENY above).
        cancelled = RowRun(_session(sample_turn))
        register_row_run(cancelled)
        mark_row_run_cancelled(cancelled.run_id)
        assert get_row_run_phase(cancelled.run_id) is RowRunPhase.CANCELLED
        assert decide_scores_row_persist(cancelled.run_id) is PersistDecision.DENY_CANCEL

        detached = RowRun(_session(sample_turn))
        register_row_run(detached)
        detach_row_run(detached.run_id)
        assert get_row_run_phase(detached.run_id) is RowRunPhase.DETACHED
        assert decide_scores_row_persist(detached.run_id) is PersistDecision.ALLOW

        retire_row_run(detached.run_id)
        assert decide_scores_row_persist(detached.run_id) is PersistDecision.REFUSE_UNKNOWN
        assert decide_scores_row_persist("never-seen") is PersistDecision.REFUSE_UNKNOWN
    finally:
        reset_tier_row_run_registry_for_tests()
