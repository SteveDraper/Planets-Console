"""Tests for pool picks by the orchestrator's published band map.

Covers the pick order over banded candidates, queued items following their
node's band, the fallback band, the band fixed at the pick, and the
single-step pin that carries no band.
"""

from __future__ import annotations

import pytest
from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.compute import (
    BandedWorkItem,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    ComputeWorkerPool,
    build_compute_registry,
    normalize_export_scope_to_compute_scope,
    pick_next_work_item,
    reset_compute_worker_pool_for_tests,
)
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
)
from api.compute.diagnostics.controller import ComputeDiagnosticsController
from api.compute.priority_band import ComputePriorityBand
from api.compute.runtime import reset_orchestrators_for_tests
from api.config import ApiConfig, set_config

from tests.compute_published_band_helpers import publish_queued_node_band
from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.test_compute_pools import (
    _ANALYTIC_ID,
    _POOL_EXPORT_REGISTRY,
    _ROW_SCOPE_KEY,
    _single_step_thread_registration,
    _work_item,
)


@pytest.fixture(autouse=True)
def _reset_pool_and_diagnostics():
    reset_compute_diagnostics_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield
    reset_compute_diagnostics_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


def _player_scope(ctx: AnalyticQueryContext, player_id: int) -> ComputeScope:
    return normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=ctx.ambient_turn,
            player_id=player_id,
        ),
        analytic_id=_ANALYTIC_ID,
        scope_key_spec=_ROW_SCOPE_KEY,
    )


def _player_scopes(sample_turn, ctx: AnalyticQueryContext, count: int) -> list[ComputeScope]:
    player_ids = [row.ownerid for row in sample_turn.scores[:count]]
    assert len(player_ids) == count
    return [_player_scope(ctx, player_id) for player_id in player_ids]


def _banded(
    scope: ComputeScope,
    *,
    band: ComputePriorityBand = "background",
    step_index: int = 0,
) -> BandedWorkItem:
    return BandedWorkItem(item=_work_item(scope=scope, step_index=step_index), priority_band=band)


def _pick_all(candidates: list[BandedWorkItem]) -> list[BandedWorkItem]:
    remaining = list(candidates)
    order: list[BandedWorkItem] = []
    while (picked := pick_next_work_item(remaining)) is not None:
        order.append(picked)
        remaining.remove(picked)
    return order


def _pool_orchestrator(
    sample_turn,
) -> tuple[ComputeWorkerPool, ComputeOrchestrator, AnalyticQueryContext]:
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((_single_step_thread_registration(),)),
        worker_pool=pool,
    )
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    return pool, orchestrator, ctx


def _bound_controller(
    orchestrator: ComputeOrchestrator,
    ctx: AnalyticQueryContext,
) -> tuple[ComputeDiagnosticsController, ShellContextKey]:
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(game_id=ctx.game_id, perspective=ctx.perspective, turn=ctx.ambient_turn)
    controller.on_shell_context(shell)
    return controller, shell


def _queued_bands(pool: ComputeWorkerPool) -> list[tuple[ComputeScope, ComputePriorityBand]]:
    return [(queued.item.scope, queued.priority_band) for queued in pool.snapshot_work_queue()]


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("background", "stream_attached"),
        ("background", "interactive_ensure"),
        ("interactive_ensure", "stream_attached"),
    ],
)
def test_pick_prefers_the_higher_band(sample_turn, lower, higher):
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    scope_a, scope_b = _player_scopes(sample_turn, ctx, 2)

    picked = pick_next_work_item([_banded(scope_a, band=lower), _banded(scope_b, band=higher)])

    assert picked is not None
    assert picked.item.scope == scope_b
    assert picked.priority_band == higher


def test_pick_takes_initial_steps_before_continuations_from_other_scopes(sample_turn):
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    scope_a, scope_b = _player_scopes(sample_turn, ctx, 2)

    order = _pick_all(
        [
            _banded(scope_a, step_index=0),
            _banded(scope_a, step_index=1),
            _banded(scope_b, step_index=0),
        ]
    )

    assert [(picked.item.scope, picked.item.step_index) for picked in order] == [
        (scope_a, 0),
        (scope_b, 0),
        (scope_a, 1),
    ]


def test_pick_takes_continuations_in_queue_order(sample_turn):
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    scope_a, scope_b = _player_scopes(sample_turn, ctx, 2)

    order = _pick_all(
        [
            _banded(scope_a, step_index=1),
            _banded(scope_b, step_index=1),
            _banded(scope_a, step_index=2),
            _banded(scope_b, step_index=2),
        ]
    )

    assert [(picked.item.scope, picked.item.step_index) for picked in order] == [
        (scope_a, 1),
        (scope_b, 1),
        (scope_a, 2),
        (scope_b, 2),
    ]


def test_queued_item_is_picked_at_its_node_band_raised_after_enqueue(sample_turn):
    pool, orchestrator, ctx = _pool_orchestrator(sample_turn)
    scope_a, scope_b = _player_scopes(sample_turn, ctx, 2)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope_a))
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope_b))
    assert _queued_bands(pool) == [(scope_a, "background"), (scope_b, "background")]

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope_b, priority_band="interactive_ensure"))

    assert _queued_bands(pool) == [(scope_a, "background"), (scope_b, "interactive_ensure")]
    picked = pool.take_next_item_for_tests()
    assert picked is not None
    assert picked.item.scope == scope_b
    assert picked.priority_band == "interactive_ensure"


def test_item_without_a_published_band_ranks_as_background(sample_turn):
    pool, orchestrator, ctx = _pool_orchestrator(sample_turn)
    # Queue-only scopes: these items are never planned, so any player ids do.
    unknown_orchestrator_scope, no_node_scope, terminal_scope, interactive_scope = (
        _player_scope(ctx, player_id) for player_id in range(1, 5)
    )
    registration_id = orchestrator.pool_registration_id
    assert registration_id is not None
    publish_queued_node_band(orchestrator, terminal_scope, "interactive_ensure")
    orchestrator.nodes[terminal_scope].state = "complete"
    publish_queued_node_band(orchestrator, interactive_scope, "interactive_ensure")
    assert orchestrator.published_band(terminal_scope) is None
    pool.enqueue_for_tests(
        _work_item(scope=unknown_orchestrator_scope, orchestrator_id=registration_id + 1)
    )
    pool.enqueue_for_tests(_work_item(scope=no_node_scope, orchestrator_id=registration_id))
    pool.enqueue_for_tests(_work_item(scope=terminal_scope, orchestrator_id=registration_id))
    pool.enqueue_for_tests(_work_item(scope=interactive_scope, orchestrator_id=registration_id))

    assert _queued_bands(pool) == [
        (unknown_orchestrator_scope, "background"),
        (no_node_scope, "background"),
        (terminal_scope, "background"),
        (interactive_scope, "interactive_ensure"),
    ]
    picks = [pool.take_next_item_for_tests() for _ in range(4)]
    assert [(picked.item.scope, picked.priority_band) for picked in picks if picked] == [
        (interactive_scope, "interactive_ensure"),
        (unknown_orchestrator_scope, "background"),
        (no_node_scope, "background"),
        (terminal_scope, "background"),
    ]


def test_picked_band_stays_fixed_when_the_published_band_changes(sample_turn):
    pool, orchestrator, ctx = _pool_orchestrator(sample_turn)
    controller, shell = _bound_controller(orchestrator, ctx)
    (scope,) = _player_scopes(sample_turn, ctx, 1)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))

    picked = pool.take_next_item_for_tests()
    assert picked is not None
    assert picked.priority_band == "background"
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope, priority_band="interactive_ensure"))
    assert orchestrator.published_band(scope) == "interactive_ensure"

    (in_flight,) = controller._in_flight_snapshot()
    assert in_flight.priority_band == "background"
    orchestrator.complete_pool_step(
        scope,
        result_wire=orchestrator.execute_pool_step(scope),
        step_kind=picked.item.step_kind,
        step_index=picked.item.step_index,
    )
    assert orchestrator.nodes[scope].state == "complete"
    (completion,) = controller._history_for_shell(shell).recent()
    assert completion.priority_band == "background"
    start, finish = (
        event for event in controller.timeline_recent(shell) if event.kind in {"start", "complete"}
    )
    assert (start.kind, start.priority_band) == ("start", "background")
    assert (finish.kind, finish.priority_band) == ("complete", "background")


def test_single_step_pin_matches_a_ready_node_whose_band_rose_after_preview(sample_turn):
    pool, orchestrator, ctx = _pool_orchestrator(sample_turn)
    controller, shell = _bound_controller(orchestrator, ctx)
    (scope,) = _player_scopes(sample_turn, ctx, 1)
    controller.set_freeze_armed(shell, freeze_armed=True)
    controller.set_allowlist(shell, frozenset({scope.player_id}))
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    assert orchestrator.nodes[scope].state == "ready"
    preview, _reason = controller.preview_single_step(shell)
    assert preview is not None
    assert (preview.source, preview.priority_band) == ("would_dispatch", "background")
    with controller._lock:
        controller._single_step.arm_from_preview(shell, preview)

    # An interactive attach raises the ready node's band, then dispatches it.
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope, priority_band="interactive_ensure"))

    node = orchestrator.nodes[scope]
    assert (node.state, node.priority_band) == ("running", "interactive_ensure")
    assert controller._single_step.dispatch_slots_remaining == 0
    picked = pool.take_next_item_for_tests()
    assert picked is not None
    assert (picked.item.scope, picked.priority_band) == (scope, "interactive_ensure")
    assert controller._single_step.grants_remaining == 0


def test_single_step_pin_matches_a_held_item_whose_band_rose_after_preview(sample_turn):
    pool, orchestrator, ctx = _pool_orchestrator(sample_turn)
    controller, shell = _bound_controller(orchestrator, ctx)
    (scope,) = _player_scopes(sample_turn, ctx, 1)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    controller.set_freeze_armed(shell, freeze_armed=True)
    controller.set_allowlist(shell, frozenset({scope.player_id}))
    preview, _reason = controller.preview_single_step(shell)
    assert preview is not None
    assert (preview.source, preview.priority_band) == ("held", "background")
    assert controller.single_step(shell) is True

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope, priority_band="interactive_ensure"))

    picked = pool.take_next_item_for_tests()
    assert picked is not None
    assert (picked.item.scope, picked.priority_band) == (scope, "interactive_ensure")
    assert controller._single_step.grants_remaining == 0
