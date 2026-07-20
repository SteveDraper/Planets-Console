"""Contract tests for scores row-run lifecycle (detach / cancel / retire).

Asserts shell identity, drain/resolution, and the production PersistDecision
gate -- not registry-internal PersistAdmission (that plane is covered by
test_persist_decision / cancel_admission suites).
"""

from __future__ import annotations

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.persist_decision import PersistDecision
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    decide_scores_row_persist,
    get_row_run,
    get_row_run_phase,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
)
from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_run_admission import RowLifecycleOp, RowRunPhase
from api.streaming.table_stream.row_stream_resolution import RowStreamResolutionState
from api.streaming.table_stream.row_stream_resolution_registry import (
    get_stream_resolution,
    reset_stream_resolution_registry_for_tests,
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


def test_apply_scores_row_lifecycle_cancel(sample_turn) -> None:
    reset_tier_row_run_registry_for_tests()
    reset_stream_resolution_registry_for_tests()
    try:
        run = RowRun(_session(sample_turn))
        register_row_run(run)
        assert not run.session.cancel_token.is_cancelled()

        apply_scores_row_lifecycle(RowLifecycleOp.CANCEL, run.run_id)

        assert get_row_run(run.run_id) is None
        assert get_row_run_phase(run.run_id) is None
        assert decide_scores_row_persist(run.run_id) == PersistDecision.refuse(should_retire=True)
        assert run.session.cancel_token.is_cancelled()
        resolution = get_stream_resolution(run.run_id)
        assert resolution is not None
        assert resolution.state is RowStreamResolutionState.CANCELED
        assert stream_drain.is_closed(run.run_id)
    finally:
        reset_tier_row_run_registry_for_tests()
        reset_stream_resolution_registry_for_tests()


def test_apply_scores_row_lifecycle_detach(sample_turn) -> None:
    reset_tier_row_run_registry_for_tests()
    reset_stream_resolution_registry_for_tests()
    try:
        run = RowRun(_session(sample_turn))
        register_row_run(run)

        apply_scores_row_lifecycle(RowLifecycleOp.DETACH, run.run_id)

        assert get_row_run(run.run_id) is run
        assert get_row_run_phase(run.run_id) is RowRunPhase.DETACHED
        assert decide_scores_row_persist(run.run_id) == PersistDecision.allow(
            retire_after_write=True
        )
        assert not run.session.cancel_token.is_cancelled()
        assert get_stream_resolution(run.run_id) is None
        assert not stream_drain.is_closed(run.run_id)
    finally:
        reset_tier_row_run_registry_for_tests()
        reset_stream_resolution_registry_for_tests()


def test_apply_scores_row_lifecycle_retire(sample_turn) -> None:
    reset_tier_row_run_registry_for_tests()
    reset_stream_resolution_registry_for_tests()
    try:
        run = RowRun(_session(sample_turn))
        register_row_run(run)
        apply_scores_row_lifecycle(RowLifecycleOp.DETACH, run.run_id)

        apply_scores_row_lifecycle(RowLifecycleOp.RETIRE, run.run_id)

        assert get_row_run(run.run_id) is None
        assert decide_scores_row_persist(run.run_id) == PersistDecision.refuse(should_retire=False)
        assert not run.session.cancel_token.is_cancelled()
    finally:
        reset_tier_row_run_registry_for_tests()
        reset_stream_resolution_registry_for_tests()
