"""A claim gives a winner its own ladder only when the serving stamp names it.

Otherwise the winner takes the ladder handed over from the stamped run, or
gets a pending rebuild from the claim's mask snapshot. The scores tier step
applies a pending rebuild first, under the run's ``tier_lock``, before the
tier job's own cancel and segment checks.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from api.analytics.military_score_inference.inference_row_runner import TierJobContinue
from api.analytics.military_score_inference.tier_ladder import LadderRebuild
from api.analytics.scores import tier_row_run_registry
from api.analytics.scores.compute_orchestration import (
    build_scores_tier_solve_job_wire,
    fleet_term,
    run_scores_tier_solve,
    scores_epoch,
)
from api.analytics.scores.export_services import resolve_scores_services
from api.analytics.scores.tier_row_run_registry import get_row_run, take_pending_rebuild
from api.compute.wire import DependencyOutputs

from tests.scores_ladder_helpers import durable_row_complete
from tests.submission_open_helpers import explicit_submission_open, live_execution

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

LEFTOVER = LadderRebuild(user_override=frozenset({99}))


def _build_wire(ladder, *, generation_offset: int = 0) -> dict:
    return build_scores_tier_solve_job_wire(
        ladder.scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ladder.ctx,
        submission_open=explicit_submission_open(),
        execution_generation=(
            ladder.orchestrator.nodes[ladder.scope].execution_generation + generation_offset
        ),
        is_execution_live=live_execution,
    )


def _mask_overrides(ladder):
    return resolve_scores_services(ladder.ctx).mask_overrides


# --- Which ladder the claim's winner runs ---


def test_a_serving_stamp_on_the_winner_keeps_its_ladder_and_a_leftover_rebuild(ladder):
    ladder.submit()
    ladder.run_tier(TierJobContinue())
    run = get_row_run(ladder.session.run_id)
    own_ladder = run.ladder
    run.pending_rebuild = LEFTOVER

    _build_wire(ladder)

    assert run.ladder is own_ladder
    assert run.pending_rebuild is LEFTOVER


def test_a_hand_over_moves_the_holders_ladder_and_its_pending_rebuild(ladder):
    ladder.submit()
    stamped_id = ladder.session.run_id
    ladder.run_tier(TierJobContinue())
    ladder.close_stream()
    winner_id = ladder.open_stream().run_id
    holder = get_row_run(stamped_id)
    holder.pending_rebuild = LEFTOVER
    held_ladder = holder.ladder

    _build_wire(ladder)

    winner = get_row_run(winner_id)
    assert winner.ladder is held_ladder
    assert winner.pending_rebuild is LEFTOVER


def test_an_indexed_background_winner_with_no_serving_stamp_gets_a_rebuild(ladder):
    ladder.submit()
    ladder.run_tier(TierJobContinue())
    ladder.close_stream()
    background = ladder.register_background_run()
    ladder.change_mask()

    wire = _build_wire(ladder, generation_offset=1)

    winner = get_row_run(background.run_id)
    assert wire["runId"] == background.run_id
    assert winner.pending_rebuild == LadderRebuild(user_override=frozenset({ladder.player_id}))


def test_a_new_execution_at_the_same_epoch_rebuilds_the_streams_own_ladder(ladder):
    ladder.submit()
    ladder.run_tier(TierJobContinue())
    run = get_row_run(ladder.session.run_id)
    assert run.pending_rebuild is None

    _build_wire(ladder, generation_offset=1)

    assert run.pending_rebuild == LadderRebuild(user_override=None)


def test_a_stale_detached_run_is_replaced_by_an_admitted_run_with_a_rebuild(ladder):
    ladder.submit()
    stream_run_id = ladder.session.run_id
    ladder.run_tier(TierJobContinue())
    ladder.close_stream()
    ladder.change_mask()

    wire = _build_wire(ladder)

    assert wire["runId"] != stream_run_id
    assert get_row_run(wire["runId"]).pending_rebuild is not None


# --- The claim epoch ---


def test_the_claim_epoch_comes_from_the_snapshot_read_before_it(ladder):
    ladder.submit()
    overrides = _mask_overrides(ladder)
    epoch_at_snapshot = scores_epoch(
        fleet_term(ladder.ctx, ladder.scope),
        overrides.revision(ladder.ctx.game_id, ladder.player_id),
    )
    snapshot = overrides.snapshot

    def snapshot_then_change(game_id, player_id):
        taken = snapshot(game_id, player_id)
        overrides.change(game_id, player_id, frozenset({1}))
        return taken

    with patch.object(overrides, "snapshot", side_effect=snapshot_then_change):
        wire = _build_wire(ladder)

    assert wire["claimEpoch"] == epoch_at_snapshot
    assert get_row_run(wire["runId"]).pending_rebuild == LadderRebuild(user_override=None)


# --- Taking and applying a pending rebuild ---


def test_taking_a_pending_rebuild_waits_for_a_claim_in_progress(ladder):
    run = get_row_run(ladder.session.run_id)
    run.pending_rebuild = LEFTOVER
    taken: list[LadderRebuild | None] = []
    taker = threading.Thread(target=lambda: taken.append(take_pending_rebuild(run)))

    with tier_row_run_registry._lock:
        taker.start()
        taker.join(timeout=0.2)
        assert taken == []
    taker.join(timeout=5)

    assert taken == [LEFTOVER]
    assert run.pending_rebuild is None


def _tier_job_spy(seen: list):
    def tier_job(run, _callbacks):
        seen.append((run.ladder, run.session.resolved_mask, run.pending_rebuild))
        run.ladder.ladder_state.ladder_complete = True
        return durable_row_complete("rebuilt")

    return patch(
        "api.analytics.scores.compute_orchestration.run_inference_tier_job",
        side_effect=tier_job,
    )


def test_a_pending_rebuild_is_applied_before_the_tier_job_runs(ladder):
    run = get_row_run(ladder.session.run_id)
    old_ladder = run.ladder
    old_ladder.ladder_state.next_step_index = 2
    run.pending_rebuild = LadderRebuild(user_override=frozenset({ladder.player_id}))
    seen: list = []

    with _tier_job_spy(seen):
        run_scores_tier_solve({"runId": run.run_id})

    ((ladder_seen, mask_seen, pending_seen),) = seen
    assert ladder_seen is not old_ladder
    assert ladder_seen.ladder_state.next_step_index == 0
    assert ladder_seen.ladder_state.resolved_mask is mask_seen
    assert mask_seen.has_user_override is True
    assert pending_seen is None


def test_a_rebuild_replaces_a_write_back_made_by_an_older_step_holding_the_lock(ladder):
    run = get_row_run(ladder.session.run_id)
    run.pending_rebuild = LadderRebuild(user_override=None)
    older_steps_ladder = run.ladder
    seen: list = []

    with _tier_job_spy(seen):
        with run.tier_lock:
            newer_step = threading.Thread(
                target=run_scores_tier_solve, args=({"runId": run.run_id},)
            )
            newer_step.start()
            newer_step.join(timeout=0.2)
            assert seen == []
            run.ladder = older_steps_ladder
        newer_step.join(timeout=5)

    ((ladder_seen, _mask, _pending),) = seen
    assert ladder_seen is not older_steps_ladder
