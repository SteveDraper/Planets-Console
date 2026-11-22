"""A scores tier terminal that does not close turn evidence fails the scores node.

No stream has to be watching, nothing has to wake the node, and a fleet node
that persist-deferred onto scores fails with the same error instead of waiting.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    scores_evidence_recovery,
)
from api.analytics.military_score_inference.inference_row_runner import (
    TierJobContinue,
    TierJobRowComplete,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.wire import StepResult
from api.exceptions import FleetScoresEvidenceOpenError, ScoresTierOutcomeError

from tests.scores_ladder_helpers import ShellLadder
from tests.walk_band_helpers import Walk, no_live_streams
from tests.walk_stop_helpers import (
    begin_pick,
    finish_step,
    pick_baseline_hop,
    take_queued_item,
    walk_node,
)

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

NON_DURABLE = TierJobRowComplete(
    row_complete=row_complete_with_summary(
        InferenceResult(status="pending", solutions=(), diagnostics={}),
        summary="not durable",
    )
)


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


def test_a_background_node_with_no_stream_fails_on_a_non_durable_terminal(sample_turn, persistence):
    ladder = ShellLadder(sample_turn, persistence)
    ladder.close_stream()
    background = ladder.register_background_run()
    ladder.submit()
    ladder.run_tier(TierJobContinue())
    submitted_before_terminal = len(ladder.submitted_work)

    ladder.run_tier(NON_DURABLE)

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "failed"
    assert isinstance(node.error, ScoresTierOutcomeError)
    assert node.error.run_id == background.run_id
    assert node.error.status == "pending"
    assert len(ladder.submitted_work) == submitted_before_terminal
    assert ladder.tier_runs == [background.run_id, background.run_id]


def test_a_fleet_node_deferred_onto_scores_fails_with_the_scores_error(sample_turn, monkeypatch):
    walk = Walk.at_shell_turn(sample_turn)
    fleet_item = pick_baseline_hop(walk)

    def defer(_policy, _ctx, scope, _result_wire):
        raise FleetScoresEvidenceOpenError(
            "scores evidence open", recovery=scores_evidence_recovery(scope)
        )

    monkeypatch.setattr(FleetPersistencePolicy, "persist", defer)
    finish_step(walk, fleet_item, StepResult(outcome="persist", payload={}))

    fleet = walk_node(walk, 3)
    scores = walk_node(walk, 3, SCORES_ANALYTIC_ID)
    assert fleet.state == "waiting_deps"
    scores_item = take_queued_item(walk)
    assert scores_item.scope == walk.scope(3, SCORES_ANALYTIC_ID)
    assert begin_pick(walk, scores_item)
    error = ScoresTierOutcomeError(run_id="scores-run", status="pending")

    walk.orchestrator.complete_pool_step(
        scores_item.scope, scores_item.execution_generation, error=error
    )

    assert scores.state == "failed"
    assert scores.error is error
    assert fleet.state == "failed"
    assert fleet.error is error
    assert walk.pool.snapshot_work_queue() == ()
