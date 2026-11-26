"""A scores tier step whose claimed RowRun is gone continues and rebuilds its wire.

Nothing has to wake the node: the re-queued step's wire build re-claims a run,
admits one, skips on closed evidence or raises.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.analytics.military_score_inference.inference_row_runner import TierJobContinue
from api.analytics.scores.tier_row_run_registry import _retire_row_run, get_row_run
from api.compute import runtime as compute_runtime
from api.compute.errors import ComputeScopeAbortedError
from api.compute.runtime import reset_orchestrators_for_tests

from tests.scores_ladder_helpers import ShellLadder, durable_row_complete

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


@pytest.fixture
def background_ladder(sample_turn, persistence, make_inference_scheduler) -> Iterator[ShellLadder]:
    """A scores node with no stream, on the process orchestrator ``cancel_run`` aborts."""
    reset_orchestrators_for_tests()
    ladder = ShellLadder(sample_turn, persistence, make_inference_scheduler)
    compute_runtime._process_orchestrator = ladder.orchestrator
    ladder.close_stream()
    ladder.submit()
    # Registered with no stream, the run takes the scheduler's background path.
    ladder.scheduler._defer_orchestrator_submit = False
    ladder.session = ladder.register_background_run()
    yield ladder
    reset_orchestrators_for_tests()


def _execute_after_the_run_is_retired(ladder: ShellLadder) -> object:
    """Build the node's tier wire, retire the run it claimed, then run the step."""
    work = ladder.submitted_work[-1]
    job_wire = work.job_wire_for(ladder.scope)
    _retire_row_run(job_wire["runId"])
    return work.run_step(job_wire)


def test_a_step_whose_run_is_gone_continues_and_the_rebuilt_wire_finishes(background_ladder):
    ladder = background_ladder
    retired_id = ladder.session.run_id

    result_wire = _execute_after_the_run_is_retired(ladder)
    assert result_wire.outcome == "continue"
    ladder.complete_tier(result_wire)

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "running"
    ladder.run_tier(durable_row_complete("finished on a re-claimed run"))

    assert node.state == "complete"
    assert ladder.persisted_summary() == "finished on a re-claimed run"
    (solved_on,) = ladder.tier_runs
    assert solved_on != retired_id
    assert get_row_run(retired_id) is None


def test_a_cancel_that_lands_before_its_abort_still_ends_the_node_as_an_abort(background_ladder):
    ladder = background_ladder
    cancelled_id = ladder.session.run_id
    work = ladder.submitted_work[-1]
    job_wire = work.job_wire_for(ladder.scope)
    assert job_wire["runId"] == cancelled_id
    abort_scope = ladder.scheduler._abort_orchestrator_scope
    held_aborts: list[tuple] = []
    ladder.scheduler._abort_orchestrator_scope = lambda *args: held_aborts.append(args)

    ladder.scheduler.cancel_run(cancelled_id)
    ladder.complete_tier(work.run_step(job_wire))
    readmitted_id = ladder.submitted_work[-1].job_wire_for(ladder.scope)["runId"]
    (held_abort,) = held_aborts
    abort_scope(*held_abort)

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "failed"
    assert isinstance(node.error, ComputeScopeAbortedError)
    assert readmitted_id != cancelled_id
    assert get_row_run(readmitted_id) is None


def test_cancelling_a_background_run_aborts_its_node(background_ladder):
    ladder = background_ladder
    ladder.run_tier(TierJobContinue())

    ladder.scheduler.cancel_run(ladder.session.run_id)

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "failed"
    assert isinstance(node.error, ComputeScopeAbortedError)
