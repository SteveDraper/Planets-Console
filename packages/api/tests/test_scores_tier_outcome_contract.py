"""A scores tier terminal that does not close turn evidence fails the scores node.

No stream has to be watching, nothing has to wake the node, and a fleet node
that persist-deferred onto scores fails with the same error instead of waiting.
A fleet node whose recovery onto scores closed nothing fails once, through the
persist-deferred recovery bound; one whose scores evidence did close finalizes.
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
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.errors import PersistDependencyRecoveryExhaustedError
from api.compute.pools import PoolWorkItem
from api.compute.wire import StepResult
from api.exceptions import FleetScoresEvidenceOpenError, ScoresTierOutcomeError

from tests.compute_lifecycle_records import record_lifecycle
from tests.on_walk_helpers import fleet_persistence
from tests.scores_exports_helpers import ADMIT_EVERY_WRITE
from tests.scores_ladder_helpers import ShellLadder, durable_row_complete, scripted_tier_job
from tests.walk_band_helpers import Walk, no_live_streams
from tests.walk_stop_helpers import (
    begin_pick,
    finish_step,
    pick_baseline_hop,
    run_step,
    take_queued_item,
    walk_node,
)

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

RECOVERY_EVENT_KINDS = ("persist_deferred", "persist_recovery_exhausted")

NON_DURABLE = TierJobRowComplete(
    row_complete=row_complete_with_summary(
        InferenceResult(status="pending", solutions=(), diagnostics={}),
        summary="not durable",
    )
)


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


def test_a_background_node_with_no_stream_fails_on_a_non_durable_terminal(
    sample_turn, persistence, make_inference_scheduler
):
    ladder = ShellLadder(sample_turn, persistence, make_inference_scheduler)
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


def _defer_the_baseline_fleet_hop_onto_scores(walk: Walk) -> PoolWorkItem:
    """Run fleet@3's real steps until its finalization defers onto scores@3; pick scores@3."""
    run_step(walk, pick_baseline_hop(walk))
    assert walk_node(walk, 3).state == "waiting_deps"
    scores_item = take_queued_item(walk)
    assert scores_item.scope == walk.scope(3, SCORES_ANALYTIC_ID)
    assert begin_pick(walk, scores_item)
    return scores_item


def test_fleet_re_deferring_after_scores_persists_no_row_fails_once(sample_turn):
    """The fleet -> scores loop: scores has no persistence, so its persist writes no row."""
    walk = Walk.solving_at_shell_turn(sample_turn, persistence=None)
    recoveries = record_lifecycle(walk.orchestrator, RECOVERY_EVENT_KINDS)
    scores_item = _defer_the_baseline_fleet_hop_onto_scores(walk)
    tier_runs: list[RowRun] = []

    with scripted_tier_job(durable_row_complete("solved"), on_tier_step=tier_runs.append):
        run_step(walk, scores_item)

    assert len(tier_runs) == 1
    assert walk_node(walk, 3, SCORES_ANALYTIC_ID).state == "complete"
    fleet = walk_node(walk, 3)
    assert fleet.state == "failed"
    assert isinstance(fleet.error, PersistDependencyRecoveryExhaustedError)
    assert fleet.error.recovery_scope == scores_item.scope
    assert [record.kind for record in recoveries] == [
        "persist_deferred",
        "persist_recovery_exhausted",
    ]
    assert walk.pool.snapshot_work_queue() == ()


def test_fleet_finalizes_when_scores_skips_on_evidence_both_read_as_closed(
    sample_turn, persistence
):
    """Scores evidence closes while scores@3 is queued, so its step skips without writing."""
    walk = Walk.solving_at_shell_turn(sample_turn, persistence=persistence)
    recoveries = record_lifecycle(walk.orchestrator, RECOVERY_EVENT_KINDS)
    scores_item = _defer_the_baseline_fleet_hop_onto_scores(walk)
    scores_scope = scores_item.scope
    persistence.persist_row_complete_guarded(
        durable_row_complete("closed by another writer").row_complete,
        guard=ADMIT_EVERY_WRITE,
        game_id=scores_scope.game_id,
        perspective=scores_scope.perspective,
        host_turn=scores_scope.turn,
        player_id=walk.player_id,
        on_walk=False,
    )
    assert ScoresPersistencePolicy().is_satisfied(walk.ctx, scores_scope)
    tier_runs: list[RowRun] = []

    with scripted_tier_job(durable_row_complete("solved"), on_tier_step=tier_runs.append):
        run_step(walk, scores_item)

    assert tier_runs == []
    assert walk_node(walk, 3, SCORES_ANALYTIC_ID).state == "complete"
    assert walk_node(walk, 3).state == "complete"
    assert fleet_persistence(walk.ctx).has_final_ledger(
        walk.ctx.game_id, walk.ctx.perspective, 3, walk.player_id
    )
    assert [record.kind for record in recoveries] == ["persist_deferred"]
    assert not any(node.state == "failed" for node in walk.orchestrator.nodes.values())
