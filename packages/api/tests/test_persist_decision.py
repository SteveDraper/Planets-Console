"""Unit tests for scores PersistDecision gate (compact cancelled admission)."""

from __future__ import annotations

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.row_run import RowRun, RowRunPhase
from api.analytics.scores import tier_row_run_registry as reg
from api.analytics.scores.persist_decision import PersistDecision, decide_scores_row_persist
from api.analytics.scores.tier_row_run_registry import (
    detach_row_run,
    get_row_run,
    get_row_run_phase,
    has_cancelled_admission,
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

        # Token alone is not a persist gate; cancel intent sets CANCELLED admission.
        run.session.cancel_token.cancel()
        assert decide_scores_row_persist(run.run_id) is PersistDecision.ALLOW

        cancelled = RowRun(_session(sample_turn))
        register_row_run(cancelled)
        mark_row_run_cancelled(cancelled.run_id)
        assert get_row_run(cancelled.run_id) is None
        assert get_row_run_phase(cancelled.run_id) is RowRunPhase.CANCELLED
        assert has_cancelled_admission(cancelled.run_id)
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


def test_cancelled_admission_fifo_eviction_refuses_persist(sample_turn, monkeypatch) -> None:
    """Past cancelled-admission bound: oldest id drops; persist REFUSE_UNKNOWN."""
    monkeypatch.setattr(reg, "MAX_CANCELLED_ADMISSIONS", 3)
    reset_tier_row_run_registry_for_tests()
    try:
        cancelled_ids: list[str] = []
        for _ in range(4):
            run = RowRun(_session(sample_turn))
            register_row_run(run)
            mark_row_run_cancelled(run.run_id)
            cancelled_ids.append(run.run_id)

        oldest = cancelled_ids[0]
        assert get_row_run(oldest) is None
        assert not has_cancelled_admission(oldest)
        assert decide_scores_row_persist(oldest) is PersistDecision.REFUSE_UNKNOWN

        for retained_id in cancelled_ids[1:]:
            assert get_row_run(retained_id) is None
            assert get_row_run_phase(retained_id) is RowRunPhase.CANCELLED
            assert decide_scores_row_persist(retained_id) is PersistDecision.DENY_CANCEL

        assert decide_scores_row_persist("never-seen") is PersistDecision.REFUSE_UNKNOWN
    finally:
        reset_tier_row_run_registry_for_tests()


def test_cancelled_fifo_does_not_evict_registered_or_detached(sample_turn, monkeypatch) -> None:
    """REGISTERED / DETACHED shells are outside cancelled-admission FIFO capacity."""
    monkeypatch.setattr(reg, "MAX_CANCELLED_ADMISSIONS", 2)
    reset_tier_row_run_registry_for_tests()
    try:
        live = RowRun(_session(sample_turn))
        register_row_run(live)

        detached = RowRun(_session(sample_turn))
        register_row_run(detached)
        detach_row_run(detached.run_id)

        for _ in range(4):
            cancelled = RowRun(_session(sample_turn))
            register_row_run(cancelled)
            mark_row_run_cancelled(cancelled.run_id)

        assert get_row_run_phase(live.run_id) is RowRunPhase.REGISTERED
        assert decide_scores_row_persist(live.run_id) is PersistDecision.ALLOW
        assert get_row_run_phase(detached.run_id) is RowRunPhase.DETACHED
        assert decide_scores_row_persist(detached.run_id) is PersistDecision.ALLOW
    finally:
        reset_tier_row_run_registry_for_tests()
