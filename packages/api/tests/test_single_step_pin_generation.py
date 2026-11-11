"""A single-step pin names the execution of its scope that it releases.

Under diagnostics freeze, a pool item left by an aborted execution can wait in
the queue next to the item its ``force_fresh`` replacement dispatched, with the
same scope and step index. A grant armed for the newer execution's item must
release that item, not the stale one, which is still dropped when it runs.
"""

from __future__ import annotations

import pytest
from api.compute import (
    ComputeOrchestrator,
    ComputeRequest,
    build_compute_registry,
    reset_compute_worker_pool_for_tests,
)
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
)
from api.compute.diagnostics.single_step_preview import preview_from_held_pool_item
from api.compute.errors import ComputeScopeAbortedError
from api.compute.runtime import reset_orchestrators_for_tests
from api.config import ApiConfig, set_config

from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.test_compute_pools import _POOL_EXPORT_REGISTRY, _scope_for_player
from tests.test_compute_stale_pool_item import _generation_echo_registration


@pytest.fixture(autouse=True)
def _diagnostics_enabled():
    reset_compute_diagnostics_for_tests()
    reset_orchestrators_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield
    reset_compute_diagnostics_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


def test_pin_for_the_newer_execution_is_not_used_up_by_a_stale_item(sample_turn):
    thread_runs: list[int] = []
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (_generation_echo_registration("thread", thread_runs),)
        ),
        worker_pool=pool,
    )
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    scope = _scope_for_player(sample_turn, sample_turn.scores[0].ownerid)
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(game_id=scope.game_id, perspective=scope.perspective, turn=scope.turn)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    assert orchestrator.abort_scope(scope, ComputeScopeAbortedError("cancelled"))
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope, force_fresh=True))
    fresh_generation = orchestrator.nodes[scope].execution_generation
    stale_held, fresh_held = pool.snapshot_work_queue()
    assert stale_held.item.step_index == fresh_held.item.step_index
    assert fresh_held.item.execution_generation == fresh_generation
    assert stale_held.item.execution_generation != fresh_generation

    controller.set_freeze_armed(shell, freeze_armed=True)
    controller.set_allowlist(shell, frozenset({scope.player_id}))
    with controller._lock:
        controller._single_step.arm_from_preview(shell, preview_from_held_pool_item(fresh_held))

    released = pool.take_next_item_for_tests()

    assert released is not None and released.item is fresh_held.item
    assert controller._single_step.grants_remaining == 0
    assert pool.take_next_item_for_tests() is None

    controller.set_freeze_armed(shell, freeze_armed=False)
    stale_picked = pool.take_next_item_for_tests()
    assert stale_picked is not None and stale_picked.item is stale_held.item
    pool._execute_item(stale_picked)

    assert thread_runs == []
    assert orchestrator.nodes[scope].state == "running"

    pool._execute_item(released)

    assert thread_runs == [fresh_generation]
    assert orchestrator.nodes[scope].state == "complete"
