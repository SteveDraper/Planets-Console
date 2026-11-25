"""A hull mask change through the Core service while a scores tier step runs.

The mask save goes through ``TurnAnalyticService``, the service the Core
hull-catalog route calls: it saves the override, drops the row at the route's
turn and makes a durable bump of the player's evidence on the ladder's
orchestrator. Whatever the bump does to the running node, no row built from
the old mask persists, and the step that runs next solves under the new mask.

- With no live row on the step's turn, the bump aborts the node: its step's
  result is ignored and a new execution rebuilds the ladder.
- With a live row there (Backfill earlier turns off), the bump keeps the
  node. The kept step's persist is discarded for an epoch retry, and the retry
  rebuilds the ladder, an accelerated split's segments included.
- A stream reopened before the retry, and a save made from another
  perspective, change neither outcome.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace

import pytest
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_NO_EXACT_SOLUTION
from api.analytics.scores.export_services import resolve_scores_services
from api.analytics.scores.tier_row_run_registry import get_row_run
from api.compute.running_step import RunningStepDisposition
from api.services.inference_hull_catalog_service import InferenceHullCatalogService
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.turn_analytic_service import TurnAnalyticService
from api.storage.memory_asset import MemoryAssetBackend

from tests.accelerated_segment_helpers import accelerated_split_orchestration
from tests.on_walk_helpers import fleet_persistence
from tests.on_walk_live_helpers import attach_stream
from tests.scores_exports_helpers import GAME_ID
from tests.scores_ladder_helpers import ShellLadder, durable_row_complete
from tests.walk_band_helpers import no_live_streams, open_scores_stream
from tests.walk_stop_helpers import assert_aborted

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

OLD_MASK_SUMMARY = "built from the old mask"
NEW_MASK_SUMMARY = "built from the new mask"


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


class _TurnsAt:
    """Turn reads that return one turn, as the Core service's turn loader would."""

    def __init__(self, turn) -> None:
        self._turn = turn

    def get_turn_info(self, _game_id: int, _perspective: int, _turn_number: int):
        return self._turn


def _save_mask_through_core(ladder: ShellLadder, *, perspective: int) -> None:
    """Save ``ladder.changed_override`` as the Core hull-catalog PUT route does."""
    turns = _TurnsAt(ladder.sample_turn)
    fleet = fleet_persistence(ladder.ctx)
    analytics = TurnAnalyticService(
        turns,
        InferenceHullCatalogService(turns, resolve_scores_services(ladder.ctx).mask_overrides),
        storage=MemoryAssetBackend(initial={}),
        inference_persistence=ladder.persistence,
        inference_invalidation=InferenceInvalidationService(
            ladder.persistence,
            fleet_persistence=fleet,
            orchestrator=lambda: ladder.orchestrator,
        ),
        fleet_persistence=fleet,
    )
    analytics.put_inference_hull_catalog_mask(
        GAME_ID, perspective, ladder.scope.turn, ladder.player_id, sorted(ladder.changed_override)
    )


@dataclass(frozen=True)
class _TierStepSeen:
    """What one tier step's run held when its tier job started."""

    run_id: str
    tier_index: int
    resolved_mask: ResolvedHullCatalogMask
    orchestration: InferenceStreamOrchestration | None
    segment_index: int | None

    @classmethod
    def of(cls, run: RowRun) -> _TierStepSeen:
        ladder_state = run.ladder.ladder_state
        orchestration = run.ladder.orchestration
        return cls(
            run_id=run.run_id,
            tier_index=ladder_state.next_step_index,
            resolved_mask=ladder_state.resolved_mask,
            orchestration=orchestration,
            segment_index=None if orchestration is None else orchestration.current_segment_index,
        )


def _run_next_step(ladder: ShellLadder) -> _TierStepSeen:
    """Run the node's next tier step to a durable row; return what it solved on."""
    seen: list[_TierStepSeen] = []
    ladder.run_tier(
        durable_row_complete(NEW_MASK_SUMMARY),
        on_tier_step=lambda run: seen.append(_TierStepSeen.of(run)),
    )
    (step,) = seen
    return step


def _ladder_score(ladder: ShellLadder):
    return next(row for row in ladder.sample_turn.scores if row.ownerid == ladder.player_id)


def _assert_solved_fresh_under_the_new_mask(ladder: ShellLadder, step: _TierStepSeen) -> None:
    assert step.tier_index == 0
    assert step.resolved_mask.user_enabled_hull_ids == ladder.changed_override
    assert ladder.persisted_summary() == NEW_MASK_SUMMARY
    assert ladder.orchestrator.nodes[ladder.scope].state == "complete"


# --- No live row: the bump aborts the running node ---


def test_a_core_mask_save_aborts_an_unwatched_step_and_the_next_execution_rebuilds(ladder):
    ladder.submit()
    aborted = ladder.orchestrator.nodes[ladder.scope]
    old_result = ladder.execute_tier(durable_row_complete(OLD_MASK_SUMMARY))

    _save_mask_through_core(ladder, perspective=ladder.scope.perspective)

    assert_aborted(aborted)
    ladder.complete_tier(old_result)
    assert ladder.persisted_summary() is None

    ladder.submit(force_fresh=True)
    assert ladder.orchestrator.nodes[ladder.scope] is not aborted
    _assert_solved_fresh_under_the_new_mask(ladder, _run_next_step(ladder))


# --- A live row on the step's turn: the bump keeps the running node ---


def _start_kept_step(ladder: ShellLadder) -> object:
    """Open a live row on the step's turn, then run a tier step to an old-mask row."""
    open_scores_stream(ladder.ctx, ladder.player_id, ladder.scope.turn)
    ladder.submit()
    assert not ladder.orchestrator.nodes[ladder.scope].submission_open.on_walk
    return ladder.execute_tier(durable_row_complete(OLD_MASK_SUMMARY))


def _assert_kept_and_discarded(ladder: ShellLadder, kept, old_result: object) -> None:
    assert ladder.orchestrator.nodes[ladder.scope] is kept
    assert kept.state == "running"
    assert kept.running_step is RunningStepDisposition.CONTINUE
    ladder.complete_tier(old_result)
    assert ladder.orchestrator.metrics.epoch_discards == 1
    assert ladder.persisted_summary() is None


def test_a_kept_step_across_a_core_mask_save_is_discarded_and_its_retry_rebuilds(ladder):
    old_result = _start_kept_step(ladder)
    kept = ladder.orchestrator.nodes[ladder.scope]

    _save_mask_through_core(ladder, perspective=ladder.scope.perspective)

    _assert_kept_and_discarded(ladder, kept, old_result)
    _assert_solved_fresh_under_the_new_mask(ladder, _run_next_step(ladder))


def test_a_kept_accelerated_split_step_restarts_its_segments_under_the_new_mask(ladder):
    run = get_row_run(ladder.session.run_id)
    run.ladder = replace(
        run.ladder,
        orchestration=accelerated_split_orchestration(ladder.sample_turn, _ladder_score(ladder)),
    )
    open_scores_stream(ladder.ctx, ladder.player_id, ladder.scope.turn)
    ladder.submit()
    kept = ladder.orchestrator.nodes[ladder.scope]
    old_segments: list[InferenceStreamOrchestration] = []

    def finish_the_first_segment(step_run: RowRun) -> None:
        orchestration = step_run.ladder.orchestration
        orchestration.record_segment_ladder_complete(
            observation=orchestration.current_observation(),
            result=InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            catalog=None,
            problem=None,
            policy_steps_attempted=[],
            step_diagnostics=[],
        )
        assert len(orchestration.segment_solves) == 1
        old_segments.append(orchestration)

    old_result = ladder.execute_tier(
        durable_row_complete(OLD_MASK_SUMMARY), on_tier_step=finish_the_first_segment
    )

    _save_mask_through_core(ladder, perspective=ladder.scope.perspective)

    _assert_kept_and_discarded(ladder, kept, old_result)
    step = _run_next_step(ladder)
    _assert_solved_fresh_under_the_new_mask(ladder, step)
    (old_orchestration,) = old_segments
    assert step.orchestration is not old_orchestration
    assert step.segment_index == 0
    assert step.orchestration.segment_solves == []


def test_a_stream_reopened_before_the_retry_solves_the_retry_under_the_new_mask(ladder):
    old_result = _start_kept_step(ladder)
    kept = ladder.orchestrator.nodes[ladder.scope]
    stamped_run_id = ladder.session.run_id

    _save_mask_through_core(ladder, perspective=ladder.scope.perspective)
    ladder.close_stream()
    reopened_run_id = ladder.open_stream().run_id

    _assert_kept_and_discarded(ladder, kept, old_result)
    step = _run_next_step(ladder)
    assert step.run_id == reopened_run_id != stamped_run_id
    _assert_solved_fresh_under_the_new_mask(ladder, step)


def test_a_core_mask_save_from_another_perspective_discards_the_running_step(ladder):
    other_perspective = ladder.scope.perspective + 1
    other_row = attach_stream(
        get_inference_table_stream_registry(),
        InferenceStreamScope(GAME_ID, other_perspective, ladder.scope.turn),
        None,
        ladder.ctx,
        [ladder.player_id],
    )
    ladder.submit()
    running = ladder.orchestrator.nodes[ladder.scope]
    old_result = ladder.execute_tier(durable_row_complete(OLD_MASK_SUMMARY))

    _save_mask_through_core(ladder, perspective=other_perspective)

    assert other_row.rescheduled_player_ids == [ladder.player_id]
    _assert_kept_and_discarded(ladder, running, old_result)
    _assert_solved_fresh_under_the_new_mask(ladder, _run_next_step(ladder))
