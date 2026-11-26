"""A detached scores row shell is kept only while its scope's ladder stamp names it.

A run whose ladder is in use is stamped: the claim stamps it before its step
runs, and the stamp is released only when the node completes or fails, after
any persist. Any other run has no step in flight and no late persist coming,
so detaching it retires it.
"""

from __future__ import annotations

import pytest
from api.analytics.scores.persist_decision import PersistDecision
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    ScopeIndexPolicy,
    StampedLadderRun,
    claim_tier_ladder,
    decide_scores_row_persist,
    get_row_run,
    get_row_run_phase,
    new_tier_row_run,
    register_row_run,
    release_tier_ladder_for_scope,
    reset_tier_row_run_registry_for_tests,
)
from api.streaming.table_stream.row_run_admission import RowLifecycleOp, RowRunPhase

from tests.scores_exports_helpers import inference_target_player_id
from tests.scores_ladder_helpers import NO_OVERRIDE_REBUILD, ladder_scope, ladder_session
from tests.submission_open_helpers import live_execution

GENERATION = 1
EPOCH = 0


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_tier_row_run_registry_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()


@pytest.fixture
def registered(sample_turn):
    player_id = inference_target_player_id(sample_turn)
    run = new_tier_row_run(ladder_session(sample_turn, player_id))
    register_row_run(run, scope_index=ScopeIndexPolicy.TAKE)
    return run, ladder_scope(sample_turn, player_id)


def _claim(scope, *, generation: int = GENERATION):
    return claim_tier_ladder(
        scope,
        execution_generation=generation,
        scores_epoch=EPOCH,
        rebuild=NO_OVERRIDE_REBUILD,
        is_execution_live=live_execution,
    )


def test_detaching_a_run_no_stamp_names_retires_it(registered) -> None:
    run, _scope = registered

    apply_scores_row_lifecycle(RowLifecycleOp.DETACH, run.run_id)

    assert get_row_run(run.run_id) is None
    assert decide_scores_row_persist(run.run_id) == PersistDecision.refuse(should_retire=False)


def test_detaching_the_stamped_run_keeps_it_detached_for_resume_and_late_persist(
    registered,
) -> None:
    run, scope = registered
    assert _claim(scope).run is run

    apply_scores_row_lifecycle(RowLifecycleOp.DETACH, run.run_id)

    assert get_row_run(run.run_id) is run
    assert get_row_run_phase(run.run_id) is RowRunPhase.DETACHED
    assert decide_scores_row_persist(run.run_id) == PersistDecision.allow(retire_after_write=True)


def test_a_stale_stamp_keeps_its_shell_until_the_next_claim_releases_it(registered) -> None:
    run, scope = registered
    assert _claim(scope).run is run
    apply_scores_row_lifecycle(RowLifecycleOp.DETACH, run.run_id)

    assert _claim(scope, generation=GENERATION + 1) is None

    assert get_row_run(run.run_id) is None


def test_a_run_whose_stamp_was_released_while_registered_is_retired_at_detach(
    registered,
) -> None:
    run, scope = registered
    assert _claim(scope).run is run
    release_tier_ladder_for_scope(StampedLadderRun(scope=scope, execution_generation=GENERATION))
    assert get_row_run_phase(run.run_id) is RowRunPhase.REGISTERED

    apply_scores_row_lifecycle(RowLifecycleOp.DETACH, run.run_id)

    assert get_row_run(run.run_id) is None
