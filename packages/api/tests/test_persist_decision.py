"""Unit tests for scores PersistDecision gate."""

from __future__ import annotations

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.cancel_fence_store import (
    mark_cancel_fence,
    reset_cancel_fence_store_for_tests,
)
from api.analytics.scores.known_run_allow_store import (
    record_known_run_allow,
    reset_known_run_allow_store_for_tests,
)
from api.analytics.scores.persist_decision import PersistDecision, decide_scores_row_persist
from api.analytics.scores.tier_row_run_registry import (
    register_row_run,
    reset_tier_row_run_registry_for_tests,
    unregister_row_run,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.scope import ComputeScope


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
    reset_cancel_fence_store_for_tests()
    reset_known_run_allow_store_for_tests()
    try:
        run = RowRun(_session(sample_turn))
        register_row_run(run)
        assert decide_scores_row_persist(run.run_id) is PersistDecision.ALLOW

        run.session.cancel_token.cancel()
        assert decide_scores_row_persist(run.run_id) is PersistDecision.DENY_CANCEL

        unregister_row_run(run.run_id)
        # Cancelled live run was unregistered without a generation fence in this
        # unit setup; known-run allow is recorded because no fence was set.
        # Explicit fence still wins over allow.
        mark_cancel_fence(
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=sample_turn.settings.turn,
                player_id=sample_turn.scores[0].ownerid,
            ),
            1,
            run_id=run.run_id,
        )
        assert decide_scores_row_persist(run.run_id) is PersistDecision.DENY_CANCEL

        allowed_id = "known-detach-run"
        record_known_run_allow(allowed_id)
        assert decide_scores_row_persist(allowed_id) is PersistDecision.ALLOW

        assert decide_scores_row_persist("never-seen") is PersistDecision.REFUSE_UNKNOWN
    finally:
        reset_tier_row_run_registry_for_tests()
        reset_cancel_fence_store_for_tests()
        reset_known_run_allow_store_for_tests()
