"""Unit tests for compute diagnostics scope, freeze, and observer wiring."""

from __future__ import annotations

import pytest
from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.export_types import ExportScope
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
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

from tests.fixtures.export_framework.harness import make_fixture_query_context
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


def test_single_step_pool_predicate_releases_one_held_item(sample_turn):
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
    pool = reset_compute_worker_pool_for_tests(worker_count=1)
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

    controller.set_freeze_armed(shell, freeze_armed=True)
    assert controller._pool_dequeue_predicate(item) is False
    controller.single_step(shell)
    assert controller._pool_dequeue_predicate(item) is True
    assert controller._pool_dequeue_predicate(item) is False


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


def test_sticky_freeze_disarms_on_game_change():
    controller = get_compute_diagnostics_controller()
    shell_a = ShellContextKey(game_id=1, perspective=1, turn=8)
    shell_b = ShellContextKey(game_id=2, perspective=1, turn=8)
    controller.set_freeze_armed(shell_a, freeze_armed=True)
    controller.on_shell_context(shell_b)
    assert controller._freeze_state.freeze_armed_for_game(1) is False
