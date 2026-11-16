"""Compute diagnostic mode covers a stale recompute of fleet and scoreboard.

A recompute behind fleet evidence generation is ordinary orchestrator work under
freeze, single-step and the allowlist. These tests drive a player's Backfill
earlier turns walk (``Walk``: a worker-less pool, so each pick is the test's)
with compute diagnostics bound to its orchestrator and the walk's shell as the
operator shell.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
    snapshot_to_wire,
)
from api.compute.diagnostics.controller import ComputeDiagnosticsController
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.pools import PoolWorkItem
from api.config import ApiConfig, set_config
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.compute_pool_test_helpers import QUEUED_ONLY_STEP_WORK
from tests.on_walk_helpers import fleet_persistence
from tests.test_backfill_walk_stop import _assert_aborted, _dropped_item_details, _node, _plant
from tests.walk_band_helpers import SHELL_TURN, Walk, end_shell, no_live_streams

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

BASELINE_TURN = 3


@pytest.fixture(autouse=True)
def _diagnostics_enabled() -> Iterator[None]:
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield from no_live_streams()
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


@pytest.fixture
def walk(sample_turn) -> Walk:
    """The player's walk with Backfill earlier turns on, at the shell turn."""
    return Walk.at_shell_turn(sample_turn)


def _diagnose(walk: Walk) -> tuple[ComputeDiagnosticsController, ShellContextKey]:
    """Bind diagnostics to the walk's orchestrator and make its shell the operator shell."""
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(walk.orchestrator)
    shell = ShellContextKey(
        game_id=walk.ctx.game_id, perspective=walk.ctx.perspective, turn=SHELL_TURN
    )
    controller.on_shell_context(shell)
    return controller, shell


def _bump(walk: Walk, host_turn: int, *, backfill_enabled: bool = True) -> None:
    """A durable bump of the walk player's evidence at ``host_turn``."""
    InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=fleet_persistence(walk.ctx),
        orchestrator=lambda: walk.orchestrator,
    ).on_inference_evidence_updated(
        walk.ctx.game_id,
        walk.ctx.perspective,
        host_turn,
        walk.player_id,
        durable=True,
        backfill_earlier_turns=backfill_enabled,
    )
    walk.orchestrator.drain_post_lock_callbacks()


def _queued_items(controller: ComputeDiagnosticsController, shell: ShellContextKey) -> list:
    return snapshot_to_wire(controller.snapshot(shell))["poolQueue"]


# --- A bump drops the hops freeze is holding ---


def test_a_bump_aborts_the_ready_hop_the_dispatch_gate_holds(walk):
    controller, shell = _diagnose(walk)
    controller.set_freeze_armed(shell, freeze_armed=True)
    walk.submit_shell()
    hop = _node(walk, BASELINE_TURN)
    assert hop.state == "ready"
    assert _queued_items(controller, shell) == []

    _bump(walk, BASELINE_TURN + 1)

    _assert_aborted(hop)
    assert walk.pool.take_next_item_for_tests() is None


def test_a_bump_drops_the_queued_hop_the_dequeue_hold_holds(walk):
    controller, shell = _diagnose(walk)
    walk.submit_shell()
    controller.set_freeze_armed(shell, freeze_armed=True)
    hop = _node(walk, BASELINE_TURN)
    assert hop.state == "running"
    assert len(_queued_items(controller, shell)) == 1
    assert walk.pool.take_next_item_for_tests() is None
    dropped = _dropped_item_details(walk.orchestrator)

    _bump(walk, BASELINE_TURN + 1)
    _assert_aborted(hop)
    (ended,) = _queued_items(controller, shell)
    assert ended["state"] == "queued"
    picked = walk.pool.take_next_item_for_tests()
    assert picked is not None and picked.item.scope == hop.scope
    walk.pool._execute_item(picked)

    assert [detail["reason"] for detail in dropped] == ["node_not_running"]
    assert _queued_items(controller, shell) == []
    assert (
        fleet_persistence(walk.ctx).get_ledger(
            walk.ctx.game_id, walk.ctx.perspective, BASELINE_TURN, walk.player_id
        )
        is None
    )


def test_with_the_setting_off_a_held_off_walk_item_on_a_live_row_turn_is_kept(walk):
    controller, shell = _diagnose(walk)
    row = walk.open_shell(turn=BASELINE_TURN)
    kept_scope = _plant(walk, turn=BASELINE_TURN, on_walk=False, state="running")
    kept: ComputeNodeRun = walk.orchestrator.nodes[kept_scope]
    walk.dispatch_pass()
    registration_id = walk.orchestrator.pool_registration_id
    assert registration_id is not None
    walk.pool.enqueue_for_tests(
        PoolWorkItem(
            orchestrator_id=registration_id,
            scope=kept_scope,
            execution_generation=kept.execution_generation,
            step_kind="materialize",
            backend="thread",
            step_index=0,
            work=QUEUED_ONLY_STEP_WORK,
        )
    )
    controller.set_freeze_armed(shell, freeze_armed=True)

    _bump(walk, SHELL_TURN, backfill_enabled=False)

    assert kept.state == "running"
    assert walk.pool.take_next_item_for_tests() is None
    assert len(_queued_items(controller, shell)) == 1
    end_shell(row)
