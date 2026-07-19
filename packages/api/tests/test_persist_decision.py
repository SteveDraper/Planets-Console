"""Unit tests for scores PersistDecision gate (scope-keyed cancelled admission)."""

from __future__ import annotations

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.persist_decision import PersistDecision, decide_scores_row_persist
from api.analytics.scores.tier_row_run_registry import (
    detach_row_run,
    get_persist_admission,
    get_row_run,
    get_row_run_phase,
    mark_row_run_cancelled,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
    retire_row_run,
    snapshot_persist_decision,
)
from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase


def _session(sample_turn, *, player_id: int | None = None) -> InferenceRowStreamSession:
    if player_id is None:
        score = sample_turn.scores[0]
    else:
        score = next(s for s in sample_turn.scores if s.ownerid == player_id)
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
        assert get_persist_admission(run.run_id) is PersistAdmission.ALLOW
        assert decide_scores_row_persist(run.run_id) == PersistDecision.allow()
        assert snapshot_persist_decision(run.run_id) == PersistDecision.allow()

        # Token alone is not a persist gate; CANCEL sets cancel admission.
        run.session.cancel_token.cancel()
        assert decide_scores_row_persist(run.run_id) == PersistDecision.allow()

        cancelled = RowRun(_session(sample_turn))
        register_row_run(cancelled)
        mark_row_run_cancelled(cancelled.run_id)
        assert get_row_run(cancelled.run_id) is None
        assert get_row_run_phase(cancelled.run_id) is None
        assert get_persist_admission(cancelled.run_id) is PersistAdmission.CANCEL_DENY
        assert decide_scores_row_persist(cancelled.run_id) == PersistDecision.refuse(
            should_retire=True
        )

        detached = RowRun(_session(sample_turn))
        register_row_run(detached)
        # Same-scope register supersedes the prior cancelled admission.
        assert get_persist_admission(cancelled.run_id) is PersistAdmission.ABSENT
        assert decide_scores_row_persist(cancelled.run_id) == PersistDecision.refuse(
            should_retire=False
        )
        detach_row_run(detached.run_id)
        assert get_row_run_phase(detached.run_id) is RowRunPhase.DETACHED
        assert get_persist_admission(detached.run_id) is PersistAdmission.ALLOW
        assert decide_scores_row_persist(detached.run_id) == PersistDecision.allow(
            retire_after_write=True
        )

        retire_row_run(detached.run_id)
        assert get_persist_admission(detached.run_id) is PersistAdmission.ABSENT
        assert decide_scores_row_persist(detached.run_id) == PersistDecision.refuse(
            should_retire=False
        )
        assert decide_scores_row_persist("never-seen") == PersistDecision.refuse(
            should_retire=False
        )
    finally:
        reset_tier_row_run_registry_for_tests()


def test_same_scope_register_supersedes_cancelled_admission(sample_turn) -> None:
    """Preempt / re-adopt clears prior cancelled denial for that scores scope."""
    reset_tier_row_run_registry_for_tests()
    try:
        first = RowRun(_session(sample_turn))
        register_row_run(first)
        mark_row_run_cancelled(first.run_id)
        assert decide_scores_row_persist(first.run_id) == PersistDecision.refuse(should_retire=True)

        replacement = RowRun(_session(sample_turn))
        register_row_run(replacement)
        assert get_persist_admission(first.run_id) is PersistAdmission.ABSENT
        assert decide_scores_row_persist(first.run_id) == PersistDecision.refuse(
            should_retire=False
        )
        assert decide_scores_row_persist(replacement.run_id) == PersistDecision.allow()
    finally:
        reset_tier_row_run_registry_for_tests()


def test_cancelled_admission_is_one_slot_per_scope(sample_turn) -> None:
    """A second cancel for the same scope replaces the prior cancelled run_id."""
    reset_tier_row_run_registry_for_tests()
    try:
        first = RowRun(_session(sample_turn))
        register_row_run(first)
        mark_row_run_cancelled(first.run_id)

        second = RowRun(_session(sample_turn))
        register_row_run(second)
        mark_row_run_cancelled(second.run_id)

        assert get_persist_admission(first.run_id) is PersistAdmission.ABSENT
        assert get_persist_admission(second.run_id) is PersistAdmission.CANCEL_DENY
        assert decide_scores_row_persist(first.run_id) == PersistDecision.refuse(
            should_retire=False
        )
        assert decide_scores_row_persist(second.run_id) == PersistDecision.refuse(
            should_retire=True
        )
    finally:
        reset_tier_row_run_registry_for_tests()


def test_cancelled_admission_does_not_cross_scopes(sample_turn) -> None:
    """Distinct player scopes keep independent cancelled admissions."""
    reset_tier_row_run_registry_for_tests()
    try:
        players = [s.ownerid for s in sample_turn.scores[:2]]
        assert len(players) == 2
        left = RowRun(_session(sample_turn, player_id=players[0]))
        right = RowRun(_session(sample_turn, player_id=players[1]))
        register_row_run(left)
        register_row_run(right)
        mark_row_run_cancelled(left.run_id)
        mark_row_run_cancelled(right.run_id)

        assert get_persist_admission(left.run_id) is PersistAdmission.CANCEL_DENY
        assert get_persist_admission(right.run_id) is PersistAdmission.CANCEL_DENY

        replacement = RowRun(_session(sample_turn, player_id=players[0]))
        register_row_run(replacement)
        assert get_persist_admission(left.run_id) is PersistAdmission.ABSENT
        assert get_persist_admission(right.run_id) is PersistAdmission.CANCEL_DENY
        assert decide_scores_row_persist(replacement.run_id) == PersistDecision.allow()
    finally:
        reset_tier_row_run_registry_for_tests()


def test_cancel_churn_does_not_drop_registered_or_detached_shells(sample_turn) -> None:
    """REGISTERED / DETACHED shells survive cancel churn on other run ids."""
    reset_tier_row_run_registry_for_tests()
    try:
        players = [s.ownerid for s in sample_turn.scores[:2]]
        assert len(players) == 2
        live = RowRun(_session(sample_turn, player_id=players[0]))
        register_row_run(live)

        detached = RowRun(_session(sample_turn, player_id=players[1]))
        register_row_run(detached)
        detach_row_run(detached.run_id)

        for _ in range(4):
            cancelled = RowRun(_session(sample_turn, player_id=players[0]))
            register_row_run(cancelled)
            mark_row_run_cancelled(cancelled.run_id)

        # live was superseded in the scope index by cancel churn, but its shell
        # remains until explicit retire (same as pre-scope-keyed behavior).
        assert get_row_run(live.run_id) is live
        assert get_row_run_phase(live.run_id) is RowRunPhase.REGISTERED
        assert decide_scores_row_persist(live.run_id) == PersistDecision.allow()
        assert get_row_run_phase(detached.run_id) is RowRunPhase.DETACHED
        assert decide_scores_row_persist(detached.run_id) == PersistDecision.allow(
            retire_after_write=True
        )
    finally:
        reset_tier_row_run_registry_for_tests()
