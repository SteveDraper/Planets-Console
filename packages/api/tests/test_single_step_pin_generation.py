"""Single-step targets the live execution of its scope.

Under diagnostics freeze, a pool item left by an aborted execution can wait in
the queue next to the item its ``force_fresh`` replacement dispatched, with the
same scope and step index. The pin names the execution it releases, so a grant
armed for the newer execution's item releases that item, not the stale one.
The preview never offers the stale item, so one step advances the scope. The
stale item is still dropped when a worker picks it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pytest
from api.analytics.export_context import AnalyticQueryContext
from api.compute import (
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    ComputeWorkerPool,
    build_compute_registry,
    reset_compute_worker_pool_for_tests,
)
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
    snapshot_to_wire,
)
from api.compute.diagnostics.controller import ComputeDiagnosticsController
from api.compute.diagnostics.single_step_preview import preview_from_held_pool_item
from api.compute.errors import ComputeScopeAbortedError
from api.compute.runtime import reset_orchestrators_for_tests
from api.config import ApiConfig, set_config

from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.test_compute_pools import _POOL_EXPORT_REGISTRY, _scope_for_player
from tests.test_compute_stale_pool_item import _generation_echo_registration

# How long the newer item runs before the stale item is picked, so a duration
# measured from the stale item's start is visibly shorter.
_FRESH_HEAD_START_SECONDS = 0.05


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


@dataclass(frozen=True)
class _AbortedScope:
    """One scope whose first execution was aborted while its pool item waits."""

    pool: ComputeWorkerPool
    orchestrator: ComputeOrchestrator
    controller: ComputeDiagnosticsController
    ctx: AnalyticQueryContext
    shell: ShellContextKey
    scope: ComputeScope
    thread_runs: list[int]

    def focus(self) -> None:
        """Arm freeze with the scope's player as the only focus player."""
        self.controller.set_freeze_armed(self.shell, freeze_armed=True)
        self.controller.set_allowlist(self.shell, frozenset({self.scope.player_id}))

    def submit_force_fresh(self) -> int:
        """Replace the aborted node and return its new execution generation."""
        self.orchestrator.submit(ComputeRequest(ctx=self.ctx, scope=self.scope, force_fresh=True))
        return self.orchestrator.nodes[self.scope].execution_generation


def _aborted_with_held_item(sample_turn) -> _AbortedScope:
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
    # Process-wide, as the runtime binds its singleton orchestrator.
    controller.bind_orchestrator(orchestrator)
    shell = ShellContextKey(game_id=scope.game_id, perspective=scope.perspective, turn=scope.turn)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    assert orchestrator.abort_scope(scope, ComputeScopeAbortedError("cancelled"))
    return _AbortedScope(
        pool=pool,
        orchestrator=orchestrator,
        controller=controller,
        ctx=ctx,
        shell=shell,
        scope=scope,
        thread_runs=thread_runs,
    )


def test_pin_for_the_newer_execution_is_not_used_up_by_a_stale_item(sample_turn):
    aborted = _aborted_with_held_item(sample_turn)
    pool, controller, orchestrator = aborted.pool, aborted.controller, aborted.orchestrator
    fresh_generation = aborted.submit_force_fresh()
    stale_held, fresh_held = pool.snapshot_work_queue()
    assert stale_held.item.step_index == fresh_held.item.step_index
    assert fresh_held.item.execution_generation == fresh_generation
    assert stale_held.item.execution_generation != fresh_generation

    aborted.focus()
    with controller._lock:
        controller._single_step.arm_from_preview(
            aborted.shell, preview_from_held_pool_item(fresh_held)
        )

    released = pool.take_next_item_for_tests()

    assert released is not None and released.item is fresh_held.item
    assert controller._single_step.grants_remaining == 0
    assert pool.take_next_item_for_tests() is None

    controller.set_freeze_armed(aborted.shell, freeze_armed=False)
    stale_picked = pool.take_next_item_for_tests()
    assert stale_picked is not None and stale_picked.item is stale_held.item
    pool._execute_item(stale_picked)

    assert aborted.thread_runs == []
    assert orchestrator.nodes[aborted.scope].state == "running"

    pool._execute_item(released)

    assert aborted.thread_runs == [fresh_generation]
    assert orchestrator.nodes[aborted.scope].state == "complete"


def test_stale_item_dropped_after_the_newer_started_leaves_the_newer_records(sample_turn):
    aborted = _aborted_with_held_item(sample_turn)
    pool, controller = aborted.pool, aborted.controller
    aborted.submit_force_fresh()
    stale_held, fresh_held = pool.snapshot_work_queue()
    aborted.focus()
    with controller._lock:
        controller._single_step.arm_from_preview(
            aborted.shell, preview_from_held_pool_item(fresh_held)
        )
    fresh_picked = pool.take_next_item_for_tests()
    assert fresh_picked is not None and fresh_picked.item is fresh_held.item
    time.sleep(_FRESH_HEAD_START_SECONDS)
    controller.set_freeze_armed(aborted.shell, freeze_armed=False)
    stale_picked = pool.take_next_item_for_tests()
    assert stale_picked is not None and stale_picked.item is stale_held.item

    pool._execute_item(stale_picked)

    in_flight = controller._in_flight_snapshot()
    assert [row.step_key for row in in_flight] == [fresh_held.item.step_key]

    pool._execute_item(fresh_picked)

    timeline = snapshot_to_wire(controller.snapshot(aborted.shell))["concurrencyTimeline"]
    fresh_start, stale_start = (event for event in timeline if event["kind"] == "start")
    (stale_dropped,) = (event for event in timeline if event["kind"] == "pool_item_dropped")
    (fresh_complete,) = (event for event in timeline if event["kind"] == "complete")
    assert not any(event["kind"] == "pool_finish_ignored" for event in timeline)
    assert stale_dropped["executionKey"] == stale_start["executionKey"]
    assert fresh_complete["executionKey"] == fresh_start["executionKey"]
    assert fresh_start["executionKey"] != stale_start["executionKey"]
    assert fresh_complete["priorityBand"] == fresh_picked.priority_band
    assert fresh_complete["durationMs"] >= _FRESH_HEAD_START_SECONDS * 1000.0
    assert controller._timeline._open_executions.close(stale_picked.item.step_key) is None


def test_preview_offers_the_newer_held_item_and_one_step_completes_it(sample_turn):
    aborted = _aborted_with_held_item(sample_turn)
    pool, controller = aborted.pool, aborted.controller
    fresh_generation = aborted.submit_force_fresh()
    _stale_held, fresh_held = pool.snapshot_work_queue()
    aborted.focus()

    preview, disabled_reason = controller.preview_single_step(aborted.shell)

    assert disabled_reason is None
    assert preview is not None
    assert (preview.source, preview.execution_generation) == ("held", fresh_generation)

    assert controller.single_step(aborted.shell)
    released = pool.take_next_item_for_tests()
    assert released is not None and released.item is fresh_held.item
    pool._execute_item(released)

    assert aborted.thread_runs == [fresh_generation]
    assert aborted.orchestrator.nodes[aborted.scope].state == "complete"


def test_preview_offers_the_newer_ready_node_over_a_stale_held_item(sample_turn):
    aborted = _aborted_with_held_item(sample_turn)
    pool, controller = aborted.pool, aborted.controller
    (stale_held,) = pool.snapshot_work_queue()
    aborted.focus()
    fresh_generation = aborted.submit_force_fresh()
    assert pool.snapshot_work_queue() == (stale_held,)
    assert aborted.orchestrator.nodes[aborted.scope].state == "ready"

    preview, disabled_reason = controller.preview_single_step(aborted.shell)

    assert disabled_reason is None
    assert preview is not None
    assert (preview.source, preview.execution_generation) == (
        "would_dispatch",
        fresh_generation,
    )

    assert controller.single_step(aborted.shell)
    released = pool.take_next_item_for_tests()
    assert released is not None
    assert released.item.execution_generation == fresh_generation
    pool._execute_item(released)

    assert aborted.thread_runs == [fresh_generation]
    assert aborted.orchestrator.nodes[aborted.scope].state == "complete"


def test_preview_does_not_offer_a_stale_held_item_alone(sample_turn):
    aborted = _aborted_with_held_item(sample_turn)
    aborted.focus()

    preview, disabled_reason = aborted.controller.preview_single_step(aborted.shell)

    assert preview is None
    assert disabled_reason == "nothing_steppable"
    assert not aborted.controller.single_step(aborted.shell)
