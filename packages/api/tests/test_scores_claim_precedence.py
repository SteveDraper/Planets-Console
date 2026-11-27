"""Which RowRun holds a scores scope: the claim's winner and the lookup's run.

Each case is asserted through both public decisions: ``get_row_run_for_scope``
first, since it changes nothing, then ``claim_tier_ladder``, which retires
the losers. The ranking is the latest ``STREAM`` run, then the stamped run,
then the earliest ``BACKGROUND`` run.
"""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    ClaimPrecedence,
    LadderClaim,
    claim_tier_ladder,
    get_row_run,
    get_row_run_for_scope,
    new_tier_row_run,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
    take_pending_rebuild,
)
from api.compute.scope import ComputeScope
from api.streaming.table_stream.row_run_admission import RowLifecycleOp, RowRunPhase

from tests.scores_exports_helpers import inference_target_player_id
from tests.scores_ladder_helpers import NO_OVERRIDE_REBUILD, ladder_scope, ladder_session
from tests.submission_open_helpers import live_execution

GENERATION = 1
EPOCH = 0

STREAM = ClaimPrecedence.STREAM
BACKGROUND = ClaimPrecedence.BACKGROUND


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_tier_row_run_registry_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()


@pytest.fixture
def scope(sample_turn) -> ComputeScope:
    return ladder_scope(sample_turn, inference_target_player_id(sample_turn))


@pytest.fixture
def register(sample_turn):
    """Register a new RowRun for the scope's player with a claim precedence."""
    player_id = inference_target_player_id(sample_turn)

    def register_run(precedence: ClaimPrecedence) -> RowRun:
        run = new_tier_row_run(ladder_session(sample_turn, player_id))
        register_row_run(run, precedence=precedence)
        return run

    return register_run


def _claim(scope: ComputeScope, *, generation: int = GENERATION) -> LadderClaim | None:
    return claim_tier_ladder(
        scope,
        execution_generation=generation,
        scores_epoch=EPOCH,
        rebuild=NO_OVERRIDE_REBUILD,
        is_execution_live=live_execution,
    )


def _stamp(scope: ComputeScope, run: RowRun) -> None:
    claim = _claim(scope)
    assert claim is not None and claim.run is run


def _assert_holder(scope: ComputeScope, holder: RowRun, *, generation: int = GENERATION) -> None:
    assert get_row_run_for_scope(scope) is holder
    claim = _claim(scope, generation=generation)
    assert claim is not None and claim.run is holder


def _cancel(run: RowRun) -> None:
    apply_scores_row_lifecycle(RowLifecycleOp.CANCEL, run.run_id)


def _detach(run: RowRun) -> None:
    apply_scores_row_lifecycle(RowLifecycleOp.DETACH, run.run_id)


def test_a_later_stream_run_beats_an_earlier_one(scope, register) -> None:
    register(STREAM)
    later = register(STREAM)

    _assert_holder(scope, later)


def test_a_stream_run_beats_the_serving_stamped_run(scope, register) -> None:
    stamped = register(STREAM)
    _stamp(scope, stamped)
    stream = register(STREAM)

    _assert_holder(scope, stream)


def test_the_serving_stamped_registered_run_beats_a_background_run(scope, register) -> None:
    stamped = register(BACKGROUND)
    _stamp(scope, stamped)
    register(BACKGROUND)

    _assert_holder(scope, stamped)


@pytest.mark.parametrize("background_first", [True, False], ids=["before", "after"])
def test_a_detached_stamped_run_holds_the_scope_against_a_background_run(
    scope, register, background_first
) -> None:
    stamped = register(STREAM)
    _stamp(scope, stamped)
    if background_first:
        background = register(BACKGROUND)
        _detach(stamped)
    else:
        _detach(stamped)
        background = register(BACKGROUND)

    assert get_row_run_for_scope(scope) is None
    claim = _claim(scope)
    assert claim is not None
    assert claim.run is stamped
    assert claim.retired_run_ids == (background.run_id,)


def test_the_earliest_background_run_wins_among_several(scope, register) -> None:
    earliest = register(BACKGROUND)
    register(BACKGROUND)
    register(BACKGROUND)

    _assert_holder(scope, earliest)


def test_a_detached_run_is_not_a_candidate(scope, register) -> None:
    detached = register(STREAM)
    _stamp(scope, detached)
    _detach(detached)
    background = register(BACKGROUND)

    # A later execution: the stamp no longer serves, so the detached run cannot win.
    claim = _claim(scope, generation=GENERATION + 1)

    assert claim is not None
    assert claim.run is background
    assert claim.retired_run_ids == (detached.run_id,)
    assert get_row_run_for_scope(scope) is background


def test_cancelling_the_stream_run_promotes_a_background_survivor(scope, register) -> None:
    stream = register(STREAM)
    survivor = register(BACKGROUND)
    _cancel(stream)

    _assert_holder(scope, survivor)


def test_cancelling_the_stream_run_promotes_an_earlier_displaced_stream_run(
    scope, register
) -> None:
    displaced = register(STREAM)
    stream = register(STREAM)
    _cancel(stream)

    _assert_holder(scope, displaced)


def test_a_background_survivor_beats_a_later_background_run_after_its_holder_left(
    scope, register
) -> None:
    stream = register(STREAM)
    survivor = register(BACKGROUND)
    _cancel(stream)
    register(BACKGROUND)

    _assert_holder(scope, survivor)


def test_a_stream_survivor_beats_a_later_background_run_after_its_holder_left(
    scope, register
) -> None:
    survivor = register(STREAM)
    stream = register(STREAM)
    _cancel(stream)
    register(BACKGROUND)

    _assert_holder(scope, survivor)


@pytest.mark.parametrize("background_first", [True, False], ids=["before", "after"])
def test_a_detached_stamped_run_resumes_its_finished_ladder_over_a_background_run(
    scope, register, background_first
) -> None:
    stamped = register(STREAM)
    _stamp(scope, stamped)
    # The run's tier steps applied its first-claim rebuild and finished the ladder.
    take_pending_rebuild(stamped)
    stamped.ladder.ladder_state.ladder_complete = True
    if background_first:
        background = register(BACKGROUND)
        _detach(stamped)
    else:
        _detach(stamped)
        background = register(BACKGROUND)

    claim = _claim(scope)

    assert claim is not None
    assert claim.run is stamped
    assert claim.ladder_handed_over is False
    assert stamped.pending_rebuild is None
    assert claim.retired_run_ids == (background.run_id,)


def test_registering_a_registered_run_again_raises(scope, register) -> None:
    run = register(STREAM)

    with pytest.raises(ValueError):
        register_row_run(run, precedence=STREAM)

    _assert_holder(scope, run)


def test_a_detached_run_may_register_again_as_the_latest_candidate(scope, register) -> None:
    detached = register(STREAM)
    _stamp(scope, detached)
    _detach(detached)
    register(STREAM)

    register_row_run(detached, precedence=STREAM)

    assert get_row_run(detached.run_id).phase is RowRunPhase.REGISTERED
    _assert_holder(scope, detached)
