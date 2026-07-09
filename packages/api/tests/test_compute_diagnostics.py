"""Unit tests for compute diagnostics scope, freeze, and observer wiring."""

from __future__ import annotations

import threading

import pytest
from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.export_types import ExportScope
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    ComputeStepSpec,
    ScopeKeySpec,
    build_compute_registry,
    normalize_export_scope_to_compute_scope,
    reset_compute_worker_pool_for_tests,
)
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
    snapshot_to_wire,
)
from api.compute.diagnostics.scope import (
    collect_diagnostic_ancestor_turns,
    scope_in_diagnostic_scope,
)
from api.compute.orchestrator import ComputeNodeRun
from api.compute.pools import PoolWorkItem
from api.compute.runtime import orchestrator_for_context, reset_orchestrators_for_tests
from api.config import ApiConfig, set_config

from tests.fixtures.export_framework.diamond_exports import SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)
from tests.test_compute_foundation import _StubPersistencePolicy


@pytest.fixture(autouse=True)
def _reset_compute_diagnostics_state():
    reset_compute_diagnostics_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=1)
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield
    reset_compute_diagnostics_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


def test_collect_diagnostic_ancestor_turns_includes_fleet_dependency_turn(sample_turn):
    from api.analytics.exports.registry import EXPORT_REGISTRY

    turns = collect_diagnostic_ancestor_turns(
        sample_turn.settings.turn,
        export_registry=EXPORT_REGISTRY,
        compute_analytic_ids=frozenset({"fleet", "scores"}),
    )
    assert sample_turn.settings.turn in turns
    assert (sample_turn.settings.turn - 1) in turns


def test_scope_in_diagnostic_scope_filters_game_and_turn():
    scope = ComputeScope(
        analytic_id="scores",
        game_id=1,
        perspective=1,
        turn=8,
        player_id=3,
    )
    assert scope_in_diagnostic_scope(
        scope,
        game_id=1,
        perspective=1,
        ancestor_turns=frozenset({8, 7}),
    )
    assert not scope_in_diagnostic_scope(
        scope,
        game_id=2,
        perspective=1,
        ancestor_turns=frozenset({8, 7}),
    )


def test_freeze_dispatch_gate_blocks_frozen_scope(sample_turn):
    ctx = make_fixture_query_context(sample_turn)
    pool = reset_compute_worker_pool_for_tests(worker_count=1)
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=build_compute_registry(()),
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    export_scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
        player_id=sample_turn.scores[0].ownerid,
    )
    scope = ComputeScope(
        analytic_id="scores",
        game_id=export_scope.game_id,
        perspective=export_scope.perspective,
        turn=export_scope.turn,
        player_id=export_scope.player_id,
    )
    node = ComputeNodeRun(scope=scope, dependency_scopes=(), state="ready")

    controller.set_freeze_armed(shell, freeze_armed=True)
    assert controller._dispatch_gate(node) is False
    controller.set_allowlist(shell, frozenset({export_scope.player_id}))
    assert controller._dispatch_gate(node) is True


def _thread_pool_registration(analytic_id: str) -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=TurnAnalyticCatalogEntry(
            id=analytic_id,
            name=analytic_id,
            supports_table=True,
            supports_map=False,
            type="selectable",
        ),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="thread"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", lambda job: {"result": job["scope"]}),),
    )


def _scores_inline_materialize_registration() -> TurnAnalyticRegistration:
    """Minimal scores registration so completion history resolves COMPUTE_REGISTRY."""
    return TurnAnalyticRegistration(
        catalog_entry=TurnAnalyticCatalogEntry(
            id="scores",
            name="scores",
            supports_table=True,
            supports_map=False,
            type="selectable",
        ),
        compute=lambda _ctx: {"analyticId": "scores"},
        export_catalog=empty_export_catalog_for("scores"),
        scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", lambda job: {"result": job["scope"]}),),
    )


def _bound_pool_orchestrator(sample_turn):
    """Bind a pool-backed orchestrator and return controller wiring for gate tests."""
    compute_registry = build_compute_registry((_thread_pool_registration(SHARED_ID),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    pool_submissions: list[ComputeScope] = []

    def pool_submitter(node, _step) -> None:
        pool_submissions.append(node.scope)

    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    export_scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
        player_id=sample_turn.scores[0].ownerid,
    )
    scope = normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id=SHARED_ID,
        scope_key_spec=compute_registry[SHARED_ID].scope_key_spec,
    )
    return controller, orchestrator, shell, scope, pool_submissions


def _player_scope(
    ctx,
    *,
    player_id: int,
    analytic_id: str,
    scope_key_spec: ScopeKeySpec,
) -> ComputeScope:
    export_scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
        player_id=player_id,
    )
    return normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id=analytic_id,
        scope_key_spec=scope_key_spec,
    )


def test_disarm_redispatches_ready_node_without_unrelated_completion(sample_turn):
    controller, orchestrator, shell, scope, pool_submissions = _bound_pool_orchestrator(sample_turn)

    controller.set_freeze_armed(shell, freeze_armed=True)
    orchestrator.submit(ComputeRequest(scope=scope))
    assert pool_submissions == []
    assert orchestrator.nodes[scope].state == "ready"
    assert orchestrator.ready_scopes() == (scope,)

    controller.set_freeze_armed(shell, freeze_armed=False)
    assert pool_submissions == [scope]
    assert orchestrator.nodes[scope].state == "running"


def test_allowlist_redispatches_ready_node_without_unrelated_completion(sample_turn):
    controller, orchestrator, shell, scope, pool_submissions = _bound_pool_orchestrator(sample_turn)

    controller.set_freeze_armed(shell, freeze_armed=True)
    orchestrator.submit(ComputeRequest(scope=scope))
    assert pool_submissions == []
    assert orchestrator.nodes[scope].state == "ready"

    controller.set_allowlist(shell, frozenset({scope.player_id}))
    assert pool_submissions == [scope]
    assert orchestrator.nodes[scope].state == "running"


def test_single_step_redispatches_ready_node_into_pool(sample_turn):
    controller, orchestrator, shell, scope, pool_submissions = _bound_pool_orchestrator(sample_turn)

    controller.set_freeze_armed(shell, freeze_armed=True)
    orchestrator.submit(ComputeRequest(scope=scope))
    assert pool_submissions == []
    assert orchestrator.nodes[scope].state == "ready"

    assert controller.single_step(shell) is True
    assert pool_submissions == [scope]
    assert orchestrator.nodes[scope].state == "running"


def test_single_step_inline_ready_clears_orphan_pool_grant(sample_turn):
    """Inline single-step must not leave a dequeue grant for a later frozen pool item."""
    from api.analytics.exports.catalog import AnalyticExportCatalog
    from api.analytics.exports.registry import merge_export_registry
    from api.analytics.scores.compute_orchestration import SCORES_MATERIALIZE

    scores_stub_export = AnalyticExportCatalog(
        analytic_id="scores",
        is_ensure_satisfied=lambda _ctx, _scope: True,
    )
    compute_registry = build_compute_registry((_scores_inline_materialize_registration(),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=merge_export_registry(scores_stub_export),
    )
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    inline_scope = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=ctx.ambient_turn,
            player_id=sample_turn.scores[0].ownerid,
        ),
        analytic_id="scores",
        scope_key_spec=compute_registry["scores"].scope_key_spec,
    )

    controller.set_freeze_armed(shell, freeze_armed=True)
    handle = orchestrator.submit(
        ComputeRequest(scope=inline_scope, step_kind=SCORES_MATERIALIZE),
    )
    assert handle.state == "ready"
    assert orchestrator.nodes[inline_scope].state == "ready"

    assert controller.single_step(shell) is True
    assert orchestrator.nodes[inline_scope].state == "complete"
    assert controller._single_step_dispatch_slots_remaining == 0
    assert controller._single_step_grants_remaining == 0
    assert controller._single_step_shell is None

    registration_id = orchestrator.pool_registration_id
    assert registration_id is not None
    later_held = PoolWorkItem(
        orchestrator_id=registration_id,
        scope=_player_scope(
            ctx,
            player_id=sample_turn.scores[1].ownerid,
            analytic_id="scores",
            scope_key_spec=compute_registry["scores"].scope_key_spec,
        ),
        step_kind="materialize",
        backend="thread",
        priority_band="background",
        step_index=0,
    )
    pool.enqueue_for_tests(later_held)
    assert controller._pool_item_is_runnable(later_held) is False
    assert pool.take_next_item_for_tests() is None


def test_single_step_releases_exactly_one_of_multiple_ready_scopes(sample_turn):
    compute_registry = build_compute_registry((_thread_pool_registration(SHARED_ID),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    pool_submissions: list[ComputeScope] = []

    def pool_submitter(node, _step) -> None:
        pool_submissions.append(node.scope)

    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    scope_a = _player_scope(
        ctx,
        player_id=sample_turn.scores[0].ownerid,
        analytic_id=SHARED_ID,
        scope_key_spec=compute_registry[SHARED_ID].scope_key_spec,
    )
    scope_b = _player_scope(
        ctx,
        player_id=sample_turn.scores[1].ownerid,
        analytic_id=SHARED_ID,
        scope_key_spec=compute_registry[SHARED_ID].scope_key_spec,
    )

    controller.set_freeze_armed(shell, freeze_armed=True)
    orchestrator.submit(ComputeRequest(scope=scope_a))
    orchestrator.submit(ComputeRequest(scope=scope_b))
    assert pool_submissions == []
    assert orchestrator.nodes[scope_a].state == "ready"
    assert orchestrator.nodes[scope_b].state == "ready"

    assert controller.single_step(shell) is True
    assert len(pool_submissions) == 1
    released = pool_submissions[0]
    held = scope_b if released == scope_a else scope_a
    assert released in {scope_a, scope_b}
    assert orchestrator.nodes[released].state == "running"
    assert orchestrator.nodes[held].state == "ready"
    assert controller._single_step_dispatch_slots_remaining == 0
    assert controller._single_step_grants_remaining == 1


def test_single_step_prefers_held_pool_item_over_ready_dispatch(sample_turn):
    compute_registry = build_compute_registry((_thread_pool_registration(SHARED_ID),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    ready_scope = _player_scope(
        ctx,
        player_id=sample_turn.scores[0].ownerid,
        analytic_id=SHARED_ID,
        scope_key_spec=compute_registry[SHARED_ID].scope_key_spec,
    )
    held_scope = _player_scope(
        ctx,
        player_id=sample_turn.scores[1].ownerid,
        analytic_id=SHARED_ID,
        scope_key_spec=compute_registry[SHARED_ID].scope_key_spec,
    )
    registration_id = orchestrator.pool_registration_id
    assert registration_id is not None
    held_item = PoolWorkItem(
        orchestrator_id=registration_id,
        scope=held_scope,
        step_kind="materialize",
        backend="thread",
        priority_band="background",
        step_index=0,
    )

    controller.set_freeze_armed(shell, freeze_armed=True)
    orchestrator.submit(ComputeRequest(scope=ready_scope))
    pool.enqueue_for_tests(held_item)
    assert orchestrator.nodes[ready_scope].state == "ready"

    assert controller.single_step(shell) is True
    assert orchestrator.nodes[ready_scope].state == "ready"
    assert controller._single_step_dispatch_slots_remaining == 0
    assert controller._single_step_grants_remaining == 1
    assert controller._pool_item_is_runnable(held_item) is True
    assert controller._single_step_grants_remaining == 1

    released = pool.take_next_item_for_tests()
    assert released is held_item
    assert controller._single_step_grants_remaining == 0
    assert controller._pool_item_is_runnable(held_item) is False


def test_single_step_pool_dequeue_releases_one_held_item(sample_turn):
    controller, pool, shell, item = _pool_held_item_fixture(sample_turn, worker_count=0)

    controller.set_freeze_armed(shell, freeze_armed=True)
    pool.enqueue_for_tests(item)
    assert controller._pool_item_is_runnable(item) is False
    controller.single_step(shell)
    assert controller._pool_item_is_runnable(item) is True
    assert controller._single_step_grants_remaining == 1

    released = pool.take_next_item_for_tests()
    assert released is item
    assert controller._single_step_grants_remaining == 0
    assert controller._pool_item_is_runnable(item) is False
    assert pool.take_next_item_for_tests() is None


def test_single_step_dequeue_selects_by_priority_without_burning_grant_on_filter(
    sample_turn,
):
    """Filter must not consume the grant while scanning lower-priority frozen items."""
    controller, pool, shell, low_item = _pool_held_item_fixture(sample_turn, worker_count=0)
    high_scope = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=shell.game_id,
            perspective=shell.perspective,
            turn=shell.turn,
            player_id=sample_turn.scores[1].ownerid,
        ),
        analytic_id="pool-analytic",
        scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
    )
    high_item = PoolWorkItem(
        orchestrator_id=low_item.orchestrator_id,
        scope=high_scope,
        step_kind="materialize",
        backend="inline",
        priority_band="stream_attached",
        step_index=0,
    )

    controller.set_freeze_armed(shell, freeze_armed=True)
    # Lower-priority frozen item is first in the queue; higher-priority second.
    pool.enqueue_for_tests(low_item)
    pool.enqueue_for_tests(high_item)
    assert controller.single_step(shell) is True
    assert controller._single_step_grants_remaining == 1

    released = pool.take_next_item_for_tests()
    assert released is high_item
    assert controller._single_step_grants_remaining == 0
    assert pool.snapshot_work_queue() == (low_item,)
    assert controller._pool_item_is_runnable(low_item) is False
    assert pool.take_next_item_for_tests() is None


def test_single_step_does_not_burn_grant_when_allowlisted_item_dequeues_first(
    sample_turn,
):
    """Allowlisted dequeue must not consume the grant meant for a held frozen item."""
    controller, pool, shell, frozen_item = _pool_held_item_fixture(sample_turn, worker_count=0)
    allowlisted_player = sample_turn.scores[1].ownerid
    allowlisted_scope = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=shell.game_id,
            perspective=shell.perspective,
            turn=shell.turn,
            player_id=allowlisted_player,
        ),
        analytic_id="pool-analytic",
        scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
    )
    allowlisted_item = PoolWorkItem(
        orchestrator_id=frozen_item.orchestrator_id,
        scope=allowlisted_scope,
        step_kind="materialize",
        backend="inline",
        priority_band="stream_attached",
        step_index=0,
    )

    controller.set_freeze_armed(shell, freeze_armed=True)
    controller.set_allowlist(shell, frozenset({allowlisted_player}))
    pool.enqueue_for_tests(frozen_item)
    pool.enqueue_for_tests(allowlisted_item)
    assert controller.single_step(shell) is True

    first = pool.take_next_item_for_tests()
    assert first is allowlisted_item
    assert controller._single_step_grants_remaining == 1

    second = pool.take_next_item_for_tests()
    assert second is frozen_item
    assert controller._single_step_grants_remaining == 0
    assert pool.take_next_item_for_tests() is None


def test_single_step_grant_releases_only_one_item_under_concurrent_dequeue(
    sample_turn,
):
    """One grant must release exactly one frozen item when two workers race dequeue."""
    controller, pool, shell, first_item = _pool_held_item_fixture(sample_turn, worker_count=0)
    second_scope = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=shell.game_id,
            perspective=shell.perspective,
            turn=shell.turn,
            player_id=sample_turn.scores[1].ownerid,
        ),
        analytic_id="pool-analytic",
        scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
    )
    second_item = PoolWorkItem(
        orchestrator_id=first_item.orchestrator_id,
        scope=second_scope,
        step_kind="materialize",
        backend="inline",
        priority_band="background",
        step_index=0,
    )

    controller.set_freeze_armed(shell, freeze_armed=True)
    pool.enqueue_for_tests(first_item)
    pool.enqueue_for_tests(second_item)
    assert controller.single_step(shell) is True
    assert controller._single_step_grants_remaining == 1

    start = threading.Barrier(2)
    released: list[PoolWorkItem | None] = []
    released_lock = threading.Lock()

    def dequeue_once() -> None:
        start.wait(timeout=2.0)
        item = pool.take_next_item_for_tests()
        with released_lock:
            released.append(item)

    workers = [threading.Thread(target=dequeue_once) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5.0)
        assert not worker.is_alive()

    non_none = [item for item in released if item is not None]
    assert len(released) == 2
    assert len(non_none) == 1
    assert non_none[0] in {first_item, second_item}
    assert controller._single_step_grants_remaining == 0
    assert len(pool.snapshot_work_queue()) == 1
    assert pool.take_next_item_for_tests() is None


def _pool_held_item_fixture(sample_turn, *, worker_count: int = 0):
    """Bind diagnostics to a pool-backed orchestrator and return one held work item."""
    registration = TurnAnalyticRegistration(
        catalog_entry=TurnAnalyticCatalogEntry(
            id="pool-analytic",
            name="pool-analytic",
            supports_table=True,
            supports_map=False,
            type="selectable",
        ),
        compute=lambda _ctx: {"analyticId": "pool-analytic"},
        export_catalog=empty_export_catalog_for("pool-analytic"),
        scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            (
                "materialize",
                lambda scope, **_kwargs: {"scope": scope.analytic_id},
            ),
        ),
        run_steps=(("materialize", lambda job: {"result": job["scope"]}),),
    )
    compute_registry = build_compute_registry((registration,))
    ctx = make_fixture_query_context(sample_turn)
    pool = reset_compute_worker_pool_for_tests(worker_count=worker_count)
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    export_scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
        player_id=sample_turn.scores[0].ownerid,
    )
    scope = normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id="pool-analytic",
        scope_key_spec=compute_registry["pool-analytic"].scope_key_spec,
    )
    registration_id = orchestrator.pool_registration_id
    assert registration_id is not None
    item = PoolWorkItem(
        orchestrator_id=registration_id,
        scope=scope,
        step_kind="materialize",
        backend="inline",
        priority_band="background",
        step_index=0,
    )
    return controller, pool, shell, item


def test_snapshot_does_not_consume_single_step_grant(sample_turn):
    controller, pool, shell, item = _pool_held_item_fixture(sample_turn, worker_count=0)

    controller.set_freeze_armed(shell, freeze_armed=True)
    pool.enqueue_for_tests(item)
    assert controller._pool_item_is_runnable(item) is False

    assert controller.single_step(shell) is True
    assert controller._single_step_grants_remaining == 1

    wire = snapshot_to_wire(controller.snapshot(shell))
    assert controller._single_step_grants_remaining == 1
    assert any(row["state"] == "queued" for row in wire["poolQueue"])
    assert controller._pool_item_is_runnable(item) is True
    assert controller._single_step_grants_remaining == 1

    released = pool.take_next_item_for_tests()
    assert released is item
    assert controller._single_step_grants_remaining == 0
    assert controller._pool_item_is_runnable(item) is False
    assert pool.take_next_item_for_tests() is None


def test_snapshot_wire_shape_includes_required_sections(sample_turn):
    ctx = make_fixture_query_context(sample_turn)
    orchestrator_for_context(ctx)
    controller = get_compute_diagnostics_controller()
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    wire = snapshot_to_wire(controller.snapshot(shell))
    assert set(wire) == {
        "shell",
        "freezeArmed",
        "allowlistedPlayerIds",
        "poolQueue",
        "dagNodes",
        "readyQueue",
        "completionHistory",
        "serverStreams",
    }
    assert wire["freezeArmed"] is False


def test_completion_history_via_orchestrator_step_complete(sample_turn):
    """Orchestrator terminal steps appear on snapshot wire completionHistory."""
    from datetime import datetime

    from api.analytics.exports.catalog import AnalyticExportCatalog
    from api.analytics.exports.registry import merge_export_registry
    from api.analytics.scores.compute_orchestration import SCORES_MATERIALIZE
    from api.compute.diagnostics.scope_key import format_compute_scope_key

    scores_stub_export = AnalyticExportCatalog(
        analytic_id="scores",
        is_ensure_satisfied=lambda _ctx, _scope: True,
    )
    compute_registry = build_compute_registry((_scores_inline_materialize_registration(),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=merge_export_registry(scores_stub_export),
    )
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    controller.on_shell_context(shell)
    scope = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=ctx.ambient_turn,
            player_id=sample_turn.scores[0].ownerid,
        ),
        analytic_id="scores",
        scope_key_spec=compute_registry["scores"].scope_key_spec,
    )

    handle = orchestrator.submit(
        ComputeRequest(scope=scope, step_kind=SCORES_MATERIALIZE),
    )
    assert handle.state == "complete"

    wire = snapshot_to_wire(controller.snapshot(shell))
    history = wire["completionHistory"]
    assert len(history) >= 1
    entry = history[-1]
    assert set(entry) == {
        "scopeKey",
        "surface",
        "terminalState",
        "stepKind",
        "stepIndex",
        "priorityBand",
        "completedAt",
    }
    assert entry["scopeKey"] == format_compute_scope_key(scope)
    assert entry["surface"] == "inline"
    assert entry["terminalState"] == "success"
    assert entry["stepKind"] == SCORES_MATERIALIZE
    assert entry["stepIndex"] == 0
    assert entry["priorityBand"] == "background"
    datetime.fromisoformat(entry["completedAt"])


def test_sticky_freeze_disarms_on_game_change():
    controller = get_compute_diagnostics_controller()
    shell_a = ShellContextKey(game_id=1, perspective=1, turn=8)
    shell_b = ShellContextKey(game_id=2, perspective=1, turn=8)
    controller.set_freeze_armed(shell_a, freeze_armed=True)
    controller.on_shell_context(shell_b)
    assert controller._freeze_state.freeze_armed_for_game(1) is False


def test_sticky_freeze_game_change_redispatches_ready_node(sample_turn):
    controller, orchestrator, shell, scope, pool_submissions = _bound_pool_orchestrator(sample_turn)

    controller.set_freeze_armed(shell, freeze_armed=True)
    orchestrator.submit(ComputeRequest(scope=scope))
    assert pool_submissions == []
    assert orchestrator.nodes[scope].state == "ready"

    other_shell = ShellContextKey(
        game_id=shell.game_id + 1,
        perspective=shell.perspective,
        turn=shell.turn,
    )
    controller.on_shell_context(other_shell)
    assert controller._freeze_state.freeze_armed_for_game(shell.game_id) is False
    assert pool_submissions == [scope]
    assert orchestrator.nodes[scope].state == "running"


def test_operator_shell_allowlist_and_history_cover_ancestor_turn_scopes(sample_turn):
    """Allowlist/history use the operator shell, not bound ambient_turn.

    Diagnosing turn N with an orchestrator bound at N-1 (fleet dependency) must
    apply the turn-N allowlist and record completions under the turn-N history.
    """
    from tests.fixtures.export_framework.harness import clone_turn_at

    operator_turn = sample_turn.settings.turn
    ancestor_turn = operator_turn - 1
    assert ancestor_turn >= 1

    # Production analytic id so completion history resolves COMPUTE_REGISTRY.
    fleet_registration = _thread_pool_registration("fleet")
    compute_registry = build_compute_registry((fleet_registration,))
    scope_key_spec = compute_registry["fleet"].scope_key_spec
    ancestor_turn_info = clone_turn_at(sample_turn, ancestor_turn)
    ancestor_ctx = make_fixture_query_context(
        ancestor_turn_info,
        stored_turns={
            operator_turn: sample_turn,
            ancestor_turn: ancestor_turn_info,
        },
    )
    assert ancestor_ctx.ambient_turn == ancestor_turn

    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    orchestrator = ComputeOrchestrator(
        ancestor_ctx,
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ancestor_ctx)

    operator_shell = ShellContextKey(
        game_id=ancestor_ctx.game_id,
        perspective=ancestor_ctx.perspective,
        turn=operator_turn,
    )
    player_id = sample_turn.scores[0].ownerid
    other_player_id = sample_turn.scores[1].ownerid
    ancestor_scope = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=ancestor_ctx.game_id,
            perspective=ancestor_ctx.perspective,
            turn=ancestor_turn,
            player_id=player_id,
        ),
        analytic_id="fleet",
        scope_key_spec=scope_key_spec,
    )
    other_ancestor_scope = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=ancestor_ctx.game_id,
            perspective=ancestor_ctx.perspective,
            turn=ancestor_turn,
            player_id=other_player_id,
        ),
        analytic_id="fleet",
        scope_key_spec=scope_key_spec,
    )

    controller.set_freeze_armed(operator_shell, freeze_armed=True)
    controller.set_allowlist(operator_shell, frozenset({player_id}))

    allowlisted_node = ComputeNodeRun(
        scope=ancestor_scope,
        dependency_scopes=(),
        state="ready",
    )
    frozen_node = ComputeNodeRun(
        scope=other_ancestor_scope,
        dependency_scopes=(),
        state="ready",
    )
    # Operator allowlist at turn N applies to ancestor-turn N-1 work.
    assert controller._dispatch_gate(allowlisted_node) is True
    assert controller._dispatch_gate(frozen_node) is False

    registration_id = orchestrator.pool_registration_id
    assert registration_id is not None
    held_item = PoolWorkItem(
        orchestrator_id=registration_id,
        scope=other_ancestor_scope,
        step_kind="materialize",
        backend="thread",
        priority_band="background",
        step_index=0,
    )
    pool.enqueue_for_tests(held_item)
    assert controller._pool_item_is_runnable(held_item) is False
    assert controller.single_step(operator_shell) is True
    assert controller._pool_item_is_runnable(held_item) is True
    assert controller._single_step_grants_remaining == 1
    assert pool.take_next_item_for_tests() is held_item
    assert controller._single_step_grants_remaining == 0

    # Production fleet step kind (history resolves against COMPUTE_REGISTRY).
    completed_node = ComputeNodeRun(
        scope=ancestor_scope,
        dependency_scopes=(),
        state="succeeded",
        profile_step_index=0,
        step_index=0,
        priority_band="interactive",
    )
    controller._on_step_complete(
        ancestor_scope,
        completed_node,
        "materialization_leg",
        "pool",
        "success",
    )
    operator_history = controller._history_for_shell(operator_shell).recent()
    assert len(operator_history) == 1
    wrong_shell = ShellContextKey(
        game_id=operator_shell.game_id,
        perspective=operator_shell.perspective,
        turn=ancestor_turn,
    )
    assert controller._history_for_shell(wrong_shell).recent() == ()
