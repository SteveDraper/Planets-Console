"""Helpers for tests that drive a Backfill earlier turns walk node by node.

They act on a ``Walk``: an orchestrator whose pool has no workers, so a test
plants nodes, picks queued items and finishes steps itself.
"""

from __future__ import annotations

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.orchestrator_state import ComputeNodeRun, NodeState
from api.compute.pools import PoolWorkItem, ThreadStepWork
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen

from tests.walk_band_helpers import SHELL_TURN, Walk

WALK_ANALYTIC_IDS = (FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID)


def walk_node(walk: Walk, turn: int, analytic_id: str = FLEET_ANALYTIC_ID) -> ComputeNodeRun:
    return walk.orchestrator.nodes[walk.scope(turn, analytic_id)]


def assert_aborted(node: ComputeNodeRun) -> None:
    assert node.state == "failed"
    assert isinstance(node.error, ComputeScopeAbortedError)


def plant_node(
    walk: Walk,
    *,
    analytic_id: str = FLEET_ANALYTIC_ID,
    turn: int = SHELL_TURN,
    game_offset: int = 0,
    perspective_offset: int = 0,
    on_walk: bool,
    state: NodeState = "parked",
    dependency_scopes: tuple[ComputeScope, ...] = (),
) -> ComputeScope:
    """Put a node no dispatch pass picks up (parked) beside the walk."""
    scope = ComputeScope(
        analytic_id=analytic_id,
        game_id=walk.ctx.game_id + game_offset,
        perspective=walk.ctx.perspective + perspective_offset,
        turn=turn,
        player_id=walk.player_id,
    )
    with walk.orchestrator._condition:
        walk.orchestrator.nodes[scope] = ComputeNodeRun(
            scope=scope,
            dependency_scopes=dependency_scopes,
            state=state,
            submission_open=SubmissionOpen(
                open_turn=turn, backfill_earlier_turns=on_walk, on_walk=on_walk
            ),
        )
    return scope


def take_queued_item(walk: Walk) -> PoolWorkItem:
    picked = walk.pool.take_next_item_for_tests()
    assert picked is not None
    return picked.item


def begin_pick(walk: Walk, item: PoolWorkItem) -> bool:
    """The worker's pick of ``item``."""
    return walk.orchestrator.begin_pool_step(
        item.scope,
        item.execution_generation,
        step_kind=item.step_kind,
        step_index=item.step_index,
    )


def pick_baseline_hop(walk: Walk) -> PoolWorkItem:
    """Submit the shell's walk and let a worker pick its baseline hop (turn 3)."""
    walk.submit_shell()
    item = take_queued_item(walk)
    assert item.scope == walk.scope(3)
    assert begin_pick(walk, item)
    return item


def finish_step(walk: Walk, item: PoolWorkItem, result_wire: object) -> None:
    walk.orchestrator.complete_pool_step(
        item.scope, item.execution_generation, result_wire=result_wire
    )


def run_step(walk: Walk, item: PoolWorkItem) -> None:
    """Build and run a picked item's real step on this thread, then hand its result back."""
    work = item.work
    job_wire = work.job_wire_for(item.scope) if isinstance(work, ThreadStepWork) else work.job_wire
    finish_step(walk, item, work.run_step(job_wire))


def non_terminal_walk_scopes(orchestrator: ComputeOrchestrator, game_id: int) -> set:
    return {
        scope
        for scope, node in orchestrator.nodes.items()
        if scope.game_id == game_id
        and scope.analytic_id in WALK_ANALYTIC_IDS
        and node.submission_open.on_walk
        and not node.is_terminal
    }
