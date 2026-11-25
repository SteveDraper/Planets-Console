"""The scores epoch carries the player's hull mask revision.

A hull mask applies to one player across every turn and perspective of a game,
so a mask save or reset moves the scores epoch of all those scopes. The
orchestrator's epoch discard and the D13 ladder stamp guard both read that
epoch, so a retained ladder built from the old mask is not resumed, not handed
over, and a step that ran across the change is discarded.
"""

from __future__ import annotations

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.military_score_inference.inference_row_runner import TierJobContinue
from api.analytics.military_score_inference.tier_ladder import LadderRebuild
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.compute_orchestration import (
    SCORES_PERSISTENCE_POLICY,
    run_scores_tier_solve,
)
from api.analytics.scores.tier_row_run_registry import get_row_run
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeScope

from tests.scores_exports_helpers import GAME_ID, scores_export_context
from tests.scores_ladder_helpers import durable_row_complete, scripted_tier_job

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

PLAYER_ID = 3
OTHER_PLAYER_ID = 4
PERSPECTIVES = (1, 2)
TURNS = (1, 2, 7)


def _scores_only_context(sample_turn):
    services = scores_export_context()
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=lambda _turn_number: None,
        export_services={SCORES_ANALYTIC_ID: services},
        game_id=GAME_ID,
        perspective=PERSPECTIVES[0],
    )
    return ctx, services


def _epochs(ctx, player_id: int) -> dict[tuple[int, int], int]:
    return {
        (perspective, turn): SCORES_PERSISTENCE_POLICY.invalidation_generation(
            ctx,
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=GAME_ID,
                perspective=perspective,
                turn=turn,
                player_id=player_id,
            ),
        )
        for perspective in PERSPECTIVES
        for turn in TURNS
    }


def test_a_mask_save_and_reset_move_the_epoch_at_every_turn_and_perspective(sample_turn):
    ctx, services = _scores_only_context(sample_turn)
    before = _epochs(ctx, PLAYER_ID)
    other_before = _epochs(ctx, OTHER_PLAYER_ID)

    services.mask_overrides.change(GAME_ID, PLAYER_ID, frozenset({1}))
    after_save = _epochs(ctx, PLAYER_ID)
    services.mask_overrides.change(GAME_ID, PLAYER_ID, None)
    after_reset = _epochs(ctx, PLAYER_ID)

    assert after_save == {key: epoch + 1 for key, epoch in before.items()}
    assert after_reset == {key: epoch + 2 for key, epoch in before.items()}
    assert _epochs(ctx, OTHER_PLAYER_ID) == other_before


def test_a_mask_change_while_detached_takes_the_admit_path(ladder):
    ladder.submit()
    stream_run_id = ladder.session.run_id
    ladder.run_tier(TierJobContinue())
    ladder.close_stream()

    ladder.change_mask()
    wire = ladder.build_wire()

    assert get_row_run(stream_run_id) is None
    assert wire["runId"] != stream_run_id


def test_a_reopen_after_a_mask_change_does_not_inherit_the_old_ladder(ladder):
    ladder.submit()
    ladder.run_tier(TierJobContinue())
    ladder.close_stream()
    winner_id = ladder.open_stream().run_id
    fresh_ladder = get_row_run(winner_id).ladder.ladder_state

    ladder.change_mask()
    wire = ladder.build_wire()

    winner = get_row_run(winner_id)
    assert wire["runId"] == winner_id
    assert winner.ladder.ladder_state is fresh_ladder
    assert fresh_ladder.next_step_index == 0
    assert winner.pending_rebuild == LadderRebuild(user_override=ladder.changed_override)

    seen: list = []
    with scripted_tier_job(
        TierJobContinue(),
        on_tier_step=lambda run: seen.append((run.ladder, run.ladder.ladder_state.next_step_index)),
    ):
        run_scores_tier_solve(wire)

    ((solved_on, tier_index),) = seen
    assert tier_index == 0
    assert solved_on.ladder_state.resolved_mask.user_enabled_hull_ids == ladder.changed_override


def test_a_step_that_ran_across_a_mask_change_is_discarded_and_requeued(ladder):
    ladder.submit()
    result_wire = ladder.execute_tier(durable_row_complete("built from the old mask"))

    ladder.change_mask()
    ladder.complete_tier(result_wire)

    assert ladder.orchestrator.metrics.epoch_discards == 1
    assert ladder.orchestrator.nodes[ladder.scope].state != "complete"
    assert ladder.persisted_summary() is None
