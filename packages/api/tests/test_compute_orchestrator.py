"""Tests for compute orchestrator DAG scheduler and singleflight."""

from __future__ import annotations

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
    DependencyOutputs,
    ScopeKeySpec,
    build_compute_registry,
    normalize_export_scope_to_compute_scope,
    plan_compute_dag,
)
from api.compute.profile import ComputeBackend

from tests.compute_pool_test_helpers import (
    run_interpreter_materialize,
    run_process_materialize,
)
from tests.fixtures.export_framework.diamond_exports import (
    BRANCH_B_ID,
    BRANCH_C_ID,
    ROOT_ID,
    SHARED_ID,
)
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    first_player_id,
    make_fixture_query_context,
)
from tests.test_compute_foundation import _StubPersistencePolicy

_ROW_SCOPE_KEY = ScopeKeySpec(axes=("perspective", "turn", "player_id"))


def _catalog_entry(analytic_id: str) -> TurnAnalyticCatalogEntry:
    return TurnAnalyticCatalogEntry(
        id=analytic_id,
        name=analytic_id,
        supports_table=True,
        supports_map=False,
        type="selectable",
    )


def _inline_compute_registration(
    analytic_id: str,
    *,
    step_kind: str = "materialize",
) -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(analytic_id),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind=step_kind, backend="inline"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            (
                step_kind,
                lambda scope, **_kwargs: {"scope": scope.analytic_id},
            ),
        ),
        run_steps=(
            (
                step_kind,
                lambda job: {"result": job["scope"]},
            ),
        ),
    )


def _two_step_inline_compute_registration(
    analytic_id: str,
    step_calls: list[str],
) -> TurnAnalyticRegistration:
    def run_tier1(job):
        step_calls.append("tier1")
        return {"result": "tier1", "scope": job["scope"]}

    def run_tier2(job):
        step_calls.append("tier2")
        return {"result": "tier2", "scope": job["scope"]}

    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(analytic_id),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(
                ComputeStepSpec(step_kind="tier1", backend="inline"),
                ComputeStepSpec(step_kind="tier2", backend="inline"),
            ),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("tier1", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
            ("tier2", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(
            ("tier1", run_tier1),
            ("tier2", run_tier2),
        ),
    )


def _thread_compute_registration(analytic_id: str) -> TurnAnalyticRegistration:
    return _pool_compute_registration(analytic_id, backend="thread")


def _pool_run_step_for_backend(backend: ComputeBackend):
    if backend == "thread":
        return lambda job: {"result": job["scope"]}
    if backend == "interpreter":
        return run_interpreter_materialize
    if backend == "process":
        return run_process_materialize
    raise ValueError(f"unsupported pool backend {backend!r}")


def _pool_compute_registration(
    analytic_id: str,
    *,
    backend: ComputeBackend,
    persistence_policy: object | None = None,
) -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(analytic_id),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend=backend),),
        ),
        persistence_policy=persistence_policy or _StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", _pool_run_step_for_backend(backend)),),
    )


def _diamond_compute_registry():
    registrations = (
        _inline_compute_registration(ROOT_ID),
        _inline_compute_registration(BRANCH_B_ID),
        _inline_compute_registration(BRANCH_C_ID),
        _inline_compute_registration(SHARED_ID),
    )
    return build_compute_registry(registrations)


def _export_scope(sample_turn) -> ExportScope:
    return ExportScope(
        game_id=sample_turn.game.id,
        perspective=1,
        turn=sample_turn.settings.turn,
        player_id=first_player_id(sample_turn),
    )


def _compute_scope(analytic_id: str, export_scope: ExportScope) -> ComputeScope:
    return normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id=analytic_id,
        scope_key_spec=_ROW_SCOPE_KEY,
    )


def test_plan_compute_dag_orders_diamond_dependencies(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    compute_registry = _diamond_compute_registry()

    planned = plan_compute_dag(
        ctx,
        ROOT_ID,
        export_scope,
        compute_registry=compute_registry,
    )

    planned_ids = [node.scope.analytic_id for node in planned]
    assert planned_ids == [SHARED_ID, BRANCH_B_ID, BRANCH_C_ID, ROOT_ID]

    root = planned[-1]
    shared_scope = planned[0].scope
    branch_b_scope = planned[1].scope
    branch_c_scope = planned[2].scope
    assert branch_b_scope in root.dependency_scopes
    assert branch_c_scope in root.dependency_scopes
    assert planned[1].dependency_scopes == (shared_scope,)
    assert planned[2].dependency_scopes == (shared_scope,)


def test_orchestrator_runs_diamond_dag_in_dependency_order(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    compute_registry = _diamond_compute_registry()
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry)

    root_scope = _compute_scope(ROOT_ID, export_scope)
    handle = orchestrator.submit(ComputeRequest(scope=root_scope))

    assert handle.state == "complete"
    assert handle.result_wire == {"result": ROOT_ID}
    assert orchestrator.metrics.inline_executions == 4
    assert orchestrator.metrics.pool_submissions == 0

    execution_order = [
        node.result_wire["result"]
        for node in orchestrator.nodes.values()
        if node.result_wire is not None
    ]
    assert execution_order.index(SHARED_ID) < execution_order.index(BRANCH_B_ID)
    assert execution_order.index(SHARED_ID) < execution_order.index(BRANCH_C_ID)
    assert execution_order.index(BRANCH_B_ID) < execution_order.index(ROOT_ID)
    assert execution_order.index(BRANCH_C_ID) < execution_order.index(ROOT_ID)


def test_blocked_nodes_are_not_ready_until_dependencies_complete(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    pool_submissions: list[str] = []

    def pool_submitter(node, _step) -> None:
        pool_submissions.append(node.scope.analytic_id)

    thread_registry = build_compute_registry(
        (
            _thread_compute_registration(ROOT_ID),
            _thread_compute_registration(BRANCH_B_ID),
            _thread_compute_registration(BRANCH_C_ID),
            _thread_compute_registration(SHARED_ID),
        )
    )
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=thread_registry,
        pool_submitter=pool_submitter,
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    orchestrator.submit(ComputeRequest(scope=root_scope))

    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    branch_c_scope = _compute_scope(BRANCH_C_ID, export_scope)

    assert orchestrator.nodes[shared_scope].state == "running"
    assert orchestrator.nodes[branch_b_scope].state == "waiting_deps"
    assert orchestrator.nodes[branch_c_scope].state == "waiting_deps"
    assert orchestrator.nodes[root_scope].state == "waiting_deps"
    assert orchestrator.ready_scopes() == ()
    assert pool_submissions == [SHARED_ID]


def test_attach_inflight_while_leader_not_terminal(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    thread_registry = build_compute_registry((_thread_compute_registration(SHARED_ID),))

    ready_orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=thread_registry,
        pool_submitter=None,
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    ready_leader = ready_orchestrator.submit(ComputeRequest(scope=shared_scope))
    ready_waiter = ready_orchestrator.submit(ComputeRequest(scope=shared_scope))

    assert ready_orchestrator.nodes[shared_scope].state == "ready"
    assert ready_leader.state == "ready"
    assert ready_waiter.state == "attach_inflight"

    diamond_registry = build_compute_registry(
        (
            _thread_compute_registration(ROOT_ID),
            _thread_compute_registration(BRANCH_B_ID),
            _thread_compute_registration(BRANCH_C_ID),
            _thread_compute_registration(SHARED_ID),
        )
    )
    deps_orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=diamond_registry,
        pool_submitter=lambda _node, _step: None,
    )
    root_scope = _compute_scope(ROOT_ID, export_scope)
    deps_leader = deps_orchestrator.submit(ComputeRequest(scope=root_scope))
    deps_waiter = deps_orchestrator.submit(ComputeRequest(scope=root_scope))

    assert deps_orchestrator.nodes[root_scope].state == "waiting_deps"
    assert deps_leader.state == "waiting_deps"
    assert deps_waiter.state == "attach_inflight"


def test_attach_inflight_does_not_double_pool_workers(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    thread_registry = build_compute_registry((_thread_compute_registration(SHARED_ID),))
    pool_submissions: list[str] = []

    def pool_submitter(node, _step) -> None:
        pool_submissions.append(node.scope.analytic_id)

    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=thread_registry,
        pool_submitter=pool_submitter,
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    leader = orchestrator.submit(ComputeRequest(scope=shared_scope))
    waiter = orchestrator.submit(ComputeRequest(scope=shared_scope))

    assert leader.state == "running"
    assert waiter.state == "attach_inflight"
    assert pool_submissions == [SHARED_ID]
    assert orchestrator.metrics.pool_submissions == 1

    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})

    assert leader.state == "complete"
    assert waiter.state == "complete"


def test_submit_does_not_run_step_before_dependencies_complete(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    inline_calls: list[str] = []

    def run_root_step(job):
        inline_calls.append(job["scope"])
        return {"result": job["scope"]}

    registrations = (
        TurnAnalyticRegistration(
            catalog_entry=_catalog_entry(ROOT_ID),
            compute=lambda _ctx: {"analyticId": ROOT_ID},
            export_catalog=empty_export_catalog_for(ROOT_ID),
            scope_key_spec=_ROW_SCOPE_KEY,
            compute_profile=AnalyticComputeProfile(
                steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
            ),
            persistence_policy=_StubPersistencePolicy(),
            build_step_job_wires=(
                ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
            ),
            run_steps=(("materialize", run_root_step),),
        ),
        _thread_compute_registration(BRANCH_B_ID),
        _thread_compute_registration(BRANCH_C_ID),
        _thread_compute_registration(SHARED_ID),
    )
    compute_registry = build_compute_registry(registrations)
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        pool_submitter=lambda _node, _step: None,
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    branch_c_scope = _compute_scope(BRANCH_C_ID, export_scope)

    orchestrator.submit(ComputeRequest(scope=root_scope))

    assert inline_calls == []
    assert orchestrator.nodes[root_scope].state == "waiting_deps"
    assert orchestrator.nodes[shared_scope].state == "running"

    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})
    assert inline_calls == []
    assert orchestrator.nodes[branch_b_scope].state == "running"

    orchestrator.complete_pool_step(branch_b_scope, result_wire={"result": BRANCH_B_ID})
    orchestrator.complete_pool_step(branch_c_scope, result_wire={"result": BRANCH_C_ID})
    orchestrator.run_until_idle()

    assert inline_calls == [ROOT_ID]
    assert orchestrator.nodes[root_scope].state == "complete"


def test_run_until_idle_terminates_after_ancestor_failure(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    thread_registry = build_compute_registry(
        (
            _thread_compute_registration(ROOT_ID),
            _thread_compute_registration(BRANCH_B_ID),
            _thread_compute_registration(BRANCH_C_ID),
            _thread_compute_registration(SHARED_ID),
        )
    )
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=thread_registry,
        pool_submitter=lambda _node, _step: None,
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    branch_c_scope = _compute_scope(BRANCH_C_ID, export_scope)

    orchestrator.submit(ComputeRequest(scope=root_scope))

    shared_failure = RuntimeError("shared step failed")
    orchestrator.complete_pool_step(shared_scope, error=shared_failure)

    orchestrator.run_until_idle()

    assert orchestrator.nodes[shared_scope].state == "failed"
    assert orchestrator.nodes[shared_scope].error is shared_failure
    assert orchestrator.nodes[branch_b_scope].state == "failed"
    assert orchestrator.nodes[branch_c_scope].state == "failed"
    assert orchestrator.nodes[root_scope].state == "failed"
    assert orchestrator.nodes[branch_b_scope].error is shared_failure
    assert orchestrator.nodes[root_scope].error is shared_failure


def test_leader_handle_exposes_error_after_inline_failure(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    inline_failure = RuntimeError("inline step failed")

    def failing_run_step(_job):
        raise inline_failure

    compute_registry = build_compute_registry(
        (
            TurnAnalyticRegistration(
                catalog_entry=_catalog_entry(SHARED_ID),
                compute=lambda _ctx: {"analyticId": SHARED_ID},
                export_catalog=empty_export_catalog_for(SHARED_ID),
                scope_key_spec=_ROW_SCOPE_KEY,
                compute_profile=AnalyticComputeProfile(
                    steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
                ),
                persistence_policy=_StubPersistencePolicy(),
                build_step_job_wires=(
                    ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
                ),
                run_steps=(("materialize", failing_run_step),),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(scope=shared_scope))

    assert handle.state == "failed"
    assert handle.error is inline_failure


def test_orchestrator_runs_multi_step_inline_profile_in_order(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    step_calls: list[str] = []
    compute_registry = build_compute_registry(
        (_two_step_inline_compute_registration(SHARED_ID, step_calls),)
    )
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(scope=shared_scope))

    assert handle.state == "complete"
    assert handle.result_wire == {"result": "tier2", "scope": SHARED_ID}
    assert step_calls == ["tier1", "tier2"]
    assert orchestrator.nodes[shared_scope].step_index == 2
    assert orchestrator.metrics.inline_executions == 2


def test_leader_handle_exposes_error_after_pool_failure(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    thread_registry = build_compute_registry((_thread_compute_registration(SHARED_ID),))
    pool_failure = RuntimeError("pool step failed")
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=thread_registry,
        pool_submitter=lambda _node, _step: None,
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(scope=shared_scope))
    assert handle.state == "running"

    orchestrator.complete_pool_step(shared_scope, error=pool_failure)

    assert handle.state == "failed"
    assert handle.error is pool_failure


class _RecordingPersistencePolicy:
    def __init__(self) -> None:
        self.generation = 0
        self.persist_calls: list[tuple[ComputeScope, object]] = []

    def is_satisfied(self, _ctx, _scope) -> bool:
        return False

    def persist(self, _ctx, scope, result_wire) -> None:
        self.persist_calls.append((scope, result_wire))

    def invalidate(self, _ctx, _scope) -> None:
        self.generation += 1

    def invalidation_generation(self, _ctx, _scope) -> int:
        return self.generation


def test_dependency_outputs_require_projects_jsonpath_slices():
    shared_scope = ComputeScope(
        analytic_id="scores",
        game_id=1,
        perspective=1,
        turn=10,
        player_id=8,
    )
    outputs = DependencyOutputs()
    outputs.put(
        shared_scope,
        {
            "solutions": [{"id": 1}],
            "meta": {"searchStatus": "complete"},
        },
    )

    slices = outputs.require(
        analytic_id="scores",
        scope=shared_scope,
        paths=("$.solutions", "$.meta.searchStatus"),
    )

    assert slices["$.solutions"] == [[{"id": 1}]]
    assert slices["$.meta.searchStatus"] == ["complete"]


def test_wire_builder_receives_dependency_slices(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    captured: list[dict[str, object]] = []

    def build_branch_b_wire(scope, *, dependency_outputs, ctx=None):
        del ctx
        captured.append(
            {
                "scope": scope.analytic_id,
                "dependency_scopes": dict(dependency_outputs.as_mapping()),
                "shared_result": dependency_outputs.require(
                    analytic_id=SHARED_ID,
                    scope=shared_scope,
                    paths=("$.result",),
                ),
            }
        )
        return {"scope": scope.analytic_id}

    compute_registry = build_compute_registry(
        (
            _inline_compute_registration(ROOT_ID),
            TurnAnalyticRegistration(
                catalog_entry=_catalog_entry(BRANCH_B_ID),
                compute=lambda _ctx: {"analyticId": BRANCH_B_ID},
                export_catalog=empty_export_catalog_for(BRANCH_B_ID),
                scope_key_spec=_ROW_SCOPE_KEY,
                compute_profile=AnalyticComputeProfile(
                    steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
                ),
                persistence_policy=_StubPersistencePolicy(),
                build_step_job_wires=(("materialize", build_branch_b_wire),),
                run_steps=(("materialize", lambda job: {"result": job["scope"]}),),
            ),
            _inline_compute_registration(BRANCH_C_ID),
            _inline_compute_registration(SHARED_ID),
        )
    )
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry)
    root_scope = _compute_scope(ROOT_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(scope=root_scope))

    assert handle.state == "complete"
    assert len(captured) == 1
    assert captured[0]["scope"] == BRANCH_B_ID
    assert shared_scope in captured[0]["dependency_scopes"]
    assert captured[0]["dependency_scopes"][shared_scope] == {"result": SHARED_ID}
    assert captured[0]["shared_result"] == {"$.result": [SHARED_ID]}
    assert orchestrator.nodes[branch_b_scope].state == "complete"


@pytest.mark.parametrize("backend", ["thread", "interpreter", "process"])
def test_stale_epoch_discards_result_and_requeues_pool_backend(sample_turn, backend):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    persistence = _RecordingPersistencePolicy()
    pool_submissions: list[tuple[str, str]] = []

    def pool_submitter(node, step, **_kwargs) -> None:
        pool_submissions.append((node.scope.analytic_id, step.backend))

    compute_registry = build_compute_registry(
        (
            _pool_compute_registration(
                SHARED_ID,
                backend=backend,
                persistence_policy=persistence,
            ),
        )
    )
    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(scope=shared_scope))
    assert handle.state == "running"
    assert pool_submissions == [(SHARED_ID, backend)]
    assert orchestrator.nodes[shared_scope].generation_at_submit == 0

    persistence.invalidate(ctx, shared_scope)
    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})

    assert orchestrator.metrics.epoch_discards == 1
    assert orchestrator.metrics.persist_calls == 0
    assert persistence.persist_calls == []
    assert handle.state == "running"
    assert pool_submissions == [(SHARED_ID, backend), (SHARED_ID, backend)]
    assert orchestrator.nodes[shared_scope].generation_at_submit == 1

    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})

    assert handle.state == "complete"
    assert orchestrator.metrics.epoch_discards == 1
    assert orchestrator.metrics.persist_calls == 1
    assert persistence.persist_calls == [(shared_scope, {"result": SHARED_ID})]


def test_stale_epoch_discards_result_and_requeues_inline(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    persistence = _RecordingPersistencePolicy()
    run_attempts = 0

    def run_materialize(job):
        nonlocal run_attempts
        run_attempts += 1
        if run_attempts == 1:
            persistence.invalidate(ctx, shared_scope)
        return {"result": job["scope"]}

    compute_registry = build_compute_registry(
        (
            TurnAnalyticRegistration(
                catalog_entry=_catalog_entry(SHARED_ID),
                compute=lambda _ctx: {"analyticId": SHARED_ID},
                export_catalog=empty_export_catalog_for(SHARED_ID),
                scope_key_spec=_ROW_SCOPE_KEY,
                compute_profile=AnalyticComputeProfile(
                    steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
                ),
                persistence_policy=persistence,
                build_step_job_wires=(
                    ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
                ),
                run_steps=(("materialize", run_materialize),),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry)

    handle = orchestrator.submit(ComputeRequest(scope=shared_scope))

    assert handle.state == "complete"
    assert run_attempts == 2
    assert orchestrator.metrics.epoch_discards == 1
    assert orchestrator.metrics.inline_executions == 2
    assert orchestrator.metrics.persist_calls == 1
    assert persistence.persist_calls == [(shared_scope, {"result": SHARED_ID})]


def test_orchestrator_persists_after_inline_node_completes(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    persistence = _RecordingPersistencePolicy()
    compute_registry = build_compute_registry(
        (
            TurnAnalyticRegistration(
                catalog_entry=_catalog_entry(SHARED_ID),
                compute=lambda _ctx: {"analyticId": SHARED_ID},
                export_catalog=empty_export_catalog_for(SHARED_ID),
                scope_key_spec=_ROW_SCOPE_KEY,
                compute_profile=AnalyticComputeProfile(
                    steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
                ),
                persistence_policy=persistence,
                build_step_job_wires=(
                    ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
                ),
                run_steps=(("materialize", lambda job: {"result": job["scope"]}),),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(scope=shared_scope))

    assert handle.state == "complete"
    assert orchestrator.metrics.persist_calls == 1
    assert persistence.persist_calls == [(shared_scope, {"result": SHARED_ID})]
