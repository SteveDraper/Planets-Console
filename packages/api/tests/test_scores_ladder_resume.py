"""A scoreboard tier ladder carries on with its own RowRun after its stream closes.

The orchestrator tests run the real scores ``tier_solve`` wire builder and step
on a pool that never runs work, with the tier job scripted. A shell whose
stream closed mid-ladder resumes only for the same node execution and scores
epoch; anything else retires it and takes the admit path.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from api.analytics.military_score_inference.inference_row_runner import (
    TierJobContinue,
)
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    ClaimPrecedence,
    StampedLadderRun,
    _detach_row_run,
    clear_row_runs,
    get_row_run,
    new_tier_row_run,
    register_row_run,
    release_tier_ladder_for_scope,
)
from api.compute import ComputeScope
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.streaming.table_stream.row_run_admission import RowLifecycleOp

from tests.scores_exports_helpers import GAME_ID, inference_target_player_id
from tests.scores_ladder_helpers import (
    CLAIM_EXECUTION_GENERATION,
    CLAIM_SCORES_EPOCH,
    claim_ladder,
    durable_row_complete,
    ladder_scope,
    ladder_session,
)

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


# --- The resume guard on the registry's ladder claim ---


@pytest.fixture
def registry_run(sample_turn) -> tuple[RowRun, ComputeScope]:
    player_id = inference_target_player_id(sample_turn)
    run = new_tier_row_run(ladder_session(sample_turn, player_id))
    register_row_run(run, precedence=ClaimPrecedence.STREAM)
    return run, ladder_scope(sample_turn, player_id)


def _claim_and_detach(run: RowRun, scope: ComputeScope) -> None:
    assert claim_ladder(scope).run is run
    _detach_row_run(run.run_id)


def test_a_detached_run_resumes_for_the_same_node_execution_and_epoch(registry_run):
    run, scope = registry_run
    _claim_and_detach(run, scope)

    assert claim_ladder(scope).run is run
    assert claim_ladder(scope).run is run


def test_a_run_detached_before_its_ladder_started_is_retired_and_does_not_resume(registry_run):
    run, scope = registry_run
    _detach_row_run(run.run_id)

    assert get_row_run(run.run_id) is None
    assert claim_ladder(scope) is None


@pytest.mark.parametrize(
    ("generation", "epoch"),
    [
        (CLAIM_EXECUTION_GENERATION + 1, CLAIM_SCORES_EPOCH),
        (CLAIM_EXECUTION_GENERATION, CLAIM_SCORES_EPOCH + 1),
    ],
    ids=["node-replaced", "epoch-changed"],
)
def test_a_mismatched_resume_retires_the_detached_shell(registry_run, generation, epoch):
    run, scope = registry_run
    _claim_and_detach(run, scope)

    assert claim_ladder(scope, execution_generation=generation, scores_epoch=epoch) is None
    assert get_row_run(run.run_id) is None
    assert claim_ladder(scope) is None


@pytest.mark.parametrize(
    "generation",
    [CLAIM_EXECUTION_GENERATION, CLAIM_EXECUTION_GENERATION + 1],
    ids=["serving", "stale"],
)
def test_a_registered_run_wins_over_the_detached_one(sample_turn, registry_run, generation):
    detached, scope = registry_run
    _claim_and_detach(detached, scope)
    reopened = new_tier_row_run(ladder_session(sample_turn, scope.player_id))
    register_row_run(reopened, precedence=ClaimPrecedence.STREAM)

    claim = claim_ladder(scope, execution_generation=generation)

    assert claim is not None
    assert claim.run is reopened
    assert claim.retired_run_ids == (detached.run_id,)
    assert get_row_run(detached.run_id) is None
    assert get_row_run(reopened.run_id) is reopened


def test_retire_after_write_clears_the_resume_entry(registry_run):
    run, scope = registry_run
    _claim_and_detach(run, scope)

    apply_scores_row_lifecycle(RowLifecycleOp.RETIRE, run.run_id)

    assert claim_ladder(scope) is None


def test_a_full_invalidate_clears_the_resume_entry(registry_run):
    run, scope = registry_run
    _claim_and_detach(run, scope)

    clear_row_runs()

    assert claim_ladder(scope) is None


def test_the_node_reaching_terminal_retires_only_its_own_entry(registry_run):
    run, scope = registry_run
    _claim_and_detach(run, scope)

    release_tier_ladder_for_scope(
        StampedLadderRun(scope=scope, execution_generation=CLAIM_EXECUTION_GENERATION - 1)
    )
    assert claim_ladder(scope).run is run

    release_tier_ladder_for_scope(
        StampedLadderRun(scope=scope, execution_generation=CLAIM_EXECUTION_GENERATION)
    )
    assert claim_ladder(scope) is None
    assert get_row_run(run.run_id) is None


@pytest.mark.parametrize("state", ["complete", "failed"])
def test_the_scope_outcome_listener_retires_the_entry_on_terminal(registry_run, state):
    run, scope = registry_run
    _claim_and_detach(run, scope)

    InferenceRowScheduler()._on_orchestrator_scope_outcome(
        ScopeLifecycleSnapshot(
            scope=scope,
            state=state,
            execution_generation=CLAIM_EXECUTION_GENERATION,
            result_wire=None,
            error=RuntimeError("hop failed") if state == "failed" else None,
        )
    )

    assert get_row_run(run.run_id) is None


# --- A ladder on the orchestrator whose stream closes mid-solve ---


def test_closing_the_stream_mid_ladder_resumes_the_same_run_to_a_durable_persist(ladder):
    ladder.submit()
    stream_run_id = ladder.session.run_id
    ladder.run_tier(TierJobContinue())

    ladder.close_stream()
    with patch("api.analytics.scores.exports.admit_scores_export_work") as admit:
        ladder.run_tier(TierJobContinue())
        ladder.run_tier(durable_row_complete("resumed after close"))
        admit.assert_not_called()

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "complete", node.error
    assert ladder.tier_runs == [stream_run_id] * 3
    assert ladder.persisted_summary() == "resumed after close"
    # ALLOW + DETACHED persists, then retires the shell after the write.
    assert get_row_run(stream_run_id) is None


def test_a_background_run_survives_its_stream_runs_cancel_and_takes_the_ladder(ladder):
    stream_run_id = ladder.session.run_id
    background_run_id = ladder.register_background_run().run_id
    ladder.submit()
    # The deferred submit skips what a live submit remembers for a later cancel.
    ladder.scheduler._remember_execution_generation_for_scope(
        ladder.scope, orchestrator=ladder.orchestrator
    )
    assert stream_run_id in ladder.scheduler._execution_generation_by_run_id

    with (
        patch.object(ladder.scheduler, "_abort_orchestrator_scope") as abort,
        patch("api.analytics.scores.exports.admit_scores_export_work") as admit,
    ):
        ladder.scheduler.cancel_run(stream_run_id)
        wire = ladder.build_wire()

    abort.assert_not_called()
    admit.assert_not_called()
    assert wire["runId"] == background_run_id
    assert list(ladder.scheduler._runs) == [background_run_id]


@pytest.mark.parametrize("stream_closed", [False, True], ids=["streams-open", "streams-closed"])
def test_a_failing_tier_fails_the_same_way_with_the_stream_open_or_closed(ladder, stream_closed):
    ladder.submit()
    ladder.run_tier(TierJobContinue())
    if stream_closed:
        ladder.close_stream()

    ladder.run_tier(RuntimeError("forced tier failure"))

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "failed"
    assert type(node.error) is RuntimeError
    assert str(node.error) == "forced tier failure"
    assert ladder.tier_runs == [ladder.session.run_id] * 2


def test_a_fleet_epoch_change_while_detached_takes_the_admit_path(ladder):
    ladder.submit()
    stream_run_id = ladder.session.run_id
    ladder.run_tier(TierJobContinue())
    ladder.close_stream()

    ladder.ctx.export_services["fleet"].persistence.invalidate_player_ledgers_from_turn(
        GAME_ID, ladder.scope.perspective, ladder.scope.turn - 1, ladder.player_id
    )
    wire = ladder.build_wire()

    assert get_row_run(stream_run_id) is None
    assert wire["runId"] != stream_run_id


def test_a_replaced_node_does_not_resume_the_old_run(ladder):
    ladder.submit()
    stream_run_id = ladder.session.run_id
    ladder.run_tier(TierJobContinue())
    ladder.close_stream()

    wire = ladder.build_wire(generation_offset=1)

    assert get_row_run(stream_run_id) is None
    assert wire["runId"] != stream_run_id
