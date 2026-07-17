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
from api.compute.wire import StepResult

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
        return StepResult(outcome="continue")

    def run_tier2(job):
        step_calls.append("tier2")
        return StepResult(
            outcome="persist",
            payload={"result": "tier2", "scope": job["scope"]},
        )

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
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)

    root_scope = _compute_scope(ROOT_ID, export_scope)
    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))

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
        compute_registry=thread_registry,
        pool_submitter=pool_submitter,
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))

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
        compute_registry=thread_registry,
        pool_submitter=None,
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    ready_leader = ready_orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    ready_waiter = ready_orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

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
        compute_registry=diamond_registry,
        pool_submitter=lambda _node, _step: None,
    )
    root_scope = _compute_scope(ROOT_ID, export_scope)
    deps_leader = deps_orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))
    deps_waiter = deps_orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))

    assert deps_orchestrator.nodes[root_scope].state == "waiting_deps"
    assert deps_leader.state == "waiting_deps"
    assert deps_waiter.state == "attach_inflight"


def test_attach_adopts_priority_band_before_execution_seal(sample_turn):
    """Higher-priority attach upgrades band until expensive execution seals (#209)."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    thread_registry = build_compute_registry((_thread_compute_registration(SHARED_ID),))
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    # No pool submitter: node stays ready (unsealed) so adopt can still run.
    orchestrator = ComputeOrchestrator(
        compute_registry=thread_registry,
        pool_submitter=None,
    )
    orchestrator.submit(
        ComputeRequest(ctx=ctx, scope=shared_scope, priority_band="background"),
    )
    assert orchestrator.nodes[shared_scope].priority_band == "background"
    assert orchestrator.nodes[shared_scope].execution_sealed is False

    waiter = orchestrator.submit(
        ComputeRequest(ctx=ctx, scope=shared_scope, priority_band="stream_attached"),
    )
    assert waiter.state == "attach_inflight"
    assert orchestrator.nodes[shared_scope].priority_band == "stream_attached"


def test_attach_does_not_adopt_priority_after_execution_seal(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    thread_registry = build_compute_registry((_thread_compute_registration(SHARED_ID),))
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    pool_submissions: list[str] = []

    def pool_submitter(node, _step) -> None:
        pool_submissions.append(node.scope.analytic_id)

    orchestrator = ComputeOrchestrator(
        compute_registry=thread_registry,
        pool_submitter=pool_submitter,
    )
    orchestrator.submit(
        ComputeRequest(ctx=ctx, scope=shared_scope, priority_band="background"),
    )
    assert orchestrator.nodes[shared_scope].state == "running"
    assert orchestrator.nodes[shared_scope].execution_sealed is True
    assert orchestrator.nodes[shared_scope].priority_band == "background"

    waiter = orchestrator.submit(
        ComputeRequest(ctx=ctx, scope=shared_scope, priority_band="stream_attached"),
    )
    assert waiter.state == "attach_inflight"
    assert orchestrator.nodes[shared_scope].priority_band == "background"
    assert pool_submissions == [SHARED_ID]


def test_compute_scope_aborted_does_not_cascade_fail_dependents(sample_turn):
    """Scores row cancel must not fail fleet dependents on the singleton DAG (#209)."""
    from api.compute.errors import ComputeScopeAbortedError

    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    compute_registry = build_compute_registry(
        (
            _thread_compute_registration(ROOT_ID),
            _thread_compute_registration(BRANCH_B_ID),
            _thread_compute_registration(BRANCH_C_ID),
            _thread_compute_registration(SHARED_ID),
        )
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        pool_submitter=lambda _node, _step: None,
    )
    root_scope = _compute_scope(ROOT_ID, export_scope)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))

    assert orchestrator.nodes[shared_scope].state == "running"
    assert orchestrator.nodes[root_scope].state == "waiting_deps"

    assert orchestrator.abort_scope(
        shared_scope,
        ComputeScopeAbortedError("scores inference row run cancelled"),
    )
    assert orchestrator.nodes[shared_scope].state == "failed"
    assert orchestrator.nodes[root_scope].state == "waiting_deps"
    assert orchestrator.nodes[root_scope].error is None


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
        compute_registry=thread_registry,
        pool_submitter=pool_submitter,
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    leader = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    waiter = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

    assert leader.state == "running"
    assert waiter.state == "attach_inflight"
    assert pool_submissions == [SHARED_ID]
    assert orchestrator.metrics.pool_submissions == 1

    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})

    assert leader.state == "complete"
    assert waiter.state == "complete"


def test_submit_reuses_terminal_node_unless_fresh_requested(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    run_payloads: list[int] = []

    def run_step(_job):
        run_payload = len(run_payloads) + 1
        run_payloads.append(run_payload)
        return {"run": run_payload}

    registration = TurnAnalyticRegistration(
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
        run_steps=(("materialize", run_step),),
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((registration,)),
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    first = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    duplicate = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    fresh = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope, force_fresh=True))

    assert run_payloads == [1, 2]
    assert first.result_wire == {"run": 1}
    assert duplicate.result_wire == {"run": 1}
    assert fresh.result_wire == {"run": 2}
    assert orchestrator.nodes[shared_scope] is fresh._node


def test_fresh_submit_replaces_failed_terminal_node(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    run_count = 0

    def run_step(_job):
        nonlocal run_count
        run_count += 1
        if run_count == 1:
            raise ValueError("first run failed")
        return {"run": run_count}

    registration = TurnAnalyticRegistration(
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
        run_steps=(("materialize", run_step),),
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((registration,)),
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    failed = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    fresh = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope, force_fresh=True))

    assert failed.state == "failed"
    assert isinstance(failed.error, ValueError)
    assert fresh.state == "complete"
    assert fresh.result_wire == {"run": 2}
    assert orchestrator.nodes[shared_scope] is fresh._node


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
        compute_registry=compute_registry,
        pool_submitter=lambda _node, _step: None,
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    branch_c_scope = _compute_scope(BRANCH_C_ID, export_scope)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))

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
        compute_registry=thread_registry,
        pool_submitter=lambda _node, _step: None,
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    branch_c_scope = _compute_scope(BRANCH_C_ID, export_scope)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))

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
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

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
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

    assert handle.state == "complete"
    assert handle.result_wire == {"result": "tier2", "scope": SHARED_ID}
    assert step_calls == ["tier1", "tier2"]
    assert orchestrator.nodes[shared_scope].step_index == 1
    assert orchestrator.nodes[shared_scope].profile_step_index == 1
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
        compute_registry=thread_registry,
        pool_submitter=lambda _node, _step: None,
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
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

    def satisfied_result_wire(self, _ctx, _scope) -> None:
        return None

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
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    root_scope = _compute_scope(ROOT_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))

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
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
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
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

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
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

    assert handle.state == "complete"
    assert orchestrator.metrics.persist_calls == 1
    assert persistence.persist_calls == [(shared_scope, {"result": SHARED_ID})]


def _outcome_compute_registration(
    analytic_id: str,
    *,
    outcome: str,
    persistence_policy: object | None = None,
) -> TurnAnalyticRegistration:
    def run_materialize(_job):
        return StepResult(outcome=outcome, payload={"result": analytic_id})

    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(analytic_id),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
        ),
        persistence_policy=persistence_policy or _StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", run_materialize),),
    )


def test_step_outcome_persist_calls_persistence_policy(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    persistence = _RecordingPersistencePolicy()
    compute_registry = build_compute_registry(
        (
            _outcome_compute_registration(
                SHARED_ID, outcome="persist", persistence_policy=persistence
            ),
        )
    )
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

    assert handle.state == "complete"
    assert handle.result_wire == {"result": SHARED_ID}
    assert orchestrator.metrics.persist_calls == 1
    assert persistence.persist_calls == [(shared_scope, {"result": SHARED_ID})]


def test_persist_finishes_before_node_complete_and_notifications(sample_turn):
    """Durable write must precede complete; notifications must follow complete.

    Historically persist ran under the orch lock with complete so dependents and
    ``has_final_ledger`` readers never saw a terminal node without a durable
    artifact. Persist is now outside the lock for deadlock reasons, but that
    ordering must still hold.
    """
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    events: list[str] = []
    durable_ready = False

    class _OrderingPersistence(_StubPersistencePolicy):
        def persist(self, _ctx, scope, result_wire):
            nonlocal durable_ready
            del scope, result_wire
            events.append("persist")
            durable_ready = True

            def _notify() -> None:
                events.append("notify")
                assert durable_ready is True

            return _notify

    registry = build_compute_registry(
        (
            _outcome_compute_registration(
                SHARED_ID,
                outcome="persist",
                persistence_policy=_OrderingPersistence(),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(compute_registry=registry)
    scope = _compute_scope(SHARED_ID, export_scope)

    def on_complete(_scope, node) -> None:
        events.append("complete_listener")
        assert node.state == "complete"
        assert durable_ready is True

    orchestrator.register_node_complete_listener(on_complete)
    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))

    assert handle.state == "complete"
    assert events == ["persist", "complete_listener", "notify"]


def test_step_outcome_complete_skips_persistence_policy(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    persistence = _RecordingPersistencePolicy()
    compute_registry = build_compute_registry(
        (
            _outcome_compute_registration(
                SHARED_ID, outcome="complete", persistence_policy=persistence
            ),
        )
    )
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

    assert handle.state == "complete"
    assert handle.result_wire == {"result": SHARED_ID}
    assert orchestrator.metrics.persist_calls == 0
    assert persistence.persist_calls == []


def test_step_outcome_continue_requeues_same_step_kind(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    run_attempts = 0

    def run_materialize(_job):
        nonlocal run_attempts
        run_attempts += 1
        if run_attempts < 3:
            return StepResult(outcome="continue")
        return StepResult(
            outcome="persist",
            payload={"result": SHARED_ID, "attempts": run_attempts},
        )

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
                run_steps=(("materialize", run_materialize),),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

    assert handle.state == "complete"
    assert run_attempts == 3
    assert orchestrator.nodes[shared_scope].step_index == 2
    assert orchestrator.metrics.inline_executions == 3


def test_submit_entry_step_kind_selects_profile_step(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    step_calls: list[str] = []

    def run_materialize(_job):
        step_calls.append("materialize")
        return StepResult(outcome="persist", payload={"result": "materialize"})

    def run_tier_solve(_job):
        step_calls.append("tier_solve")
        return StepResult(outcome="complete", payload={"result": "tier_solve"})

    compute_registry = build_compute_registry(
        (
            TurnAnalyticRegistration(
                catalog_entry=_catalog_entry(SHARED_ID),
                compute=lambda _ctx: {"analyticId": SHARED_ID},
                export_catalog=empty_export_catalog_for(SHARED_ID),
                scope_key_spec=_ROW_SCOPE_KEY,
                compute_profile=AnalyticComputeProfile(
                    steps=(
                        ComputeStepSpec(step_kind="materialize", backend="inline"),
                        ComputeStepSpec(step_kind="tier_solve", backend="inline"),
                    ),
                ),
                persistence_policy=_StubPersistencePolicy(),
                build_step_job_wires=(
                    ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
                    ("tier_solve", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
                ),
                run_steps=(
                    ("materialize", run_materialize),
                    ("tier_solve", run_tier_solve),
                ),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    handle = orchestrator.submit(
        ComputeRequest(ctx=ctx, scope=shared_scope, step_kind="tier_solve"),
    )

    assert handle.state == "complete"
    assert step_calls == ["tier_solve"]
    assert handle.result_wire == {"result": "tier_solve"}
    assert orchestrator.nodes[shared_scope].profile_step_index == 1


def test_dispatch_gate_skips_gated_ready_nodes_without_starving_others(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    pool_submissions: list[str] = []
    gated_analytic_id = BRANCH_B_ID

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
        compute_registry=thread_registry,
        pool_submitter=pool_submitter,
    )
    orchestrator.register_dispatch_gate(
        lambda node: node.scope.analytic_id != gated_analytic_id,
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    branch_c_scope = _compute_scope(BRANCH_C_ID, export_scope)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))

    assert orchestrator.nodes[shared_scope].state == "running"
    assert orchestrator.nodes[branch_b_scope].state == "waiting_deps"
    assert orchestrator.nodes[branch_c_scope].state == "waiting_deps"

    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})

    assert orchestrator.nodes[branch_c_scope].state == "running"
    assert orchestrator.nodes[branch_b_scope].state == "ready"
    assert pool_submissions == [SHARED_ID, BRANCH_C_ID]
    assert orchestrator.ready_scopes() == (branch_b_scope,)


def test_pool_submitter_never_runs_while_orchestrator_lock_is_held(sample_turn):
    """Pool submit must not nest under the orchestrator lock (deadlock with pool→controller)."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    submit_calls = 0

    thread_registry = build_compute_registry(
        (
            _thread_compute_registration(ROOT_ID),
            _thread_compute_registration(BRANCH_B_ID),
            _thread_compute_registration(BRANCH_C_ID),
            _thread_compute_registration(SHARED_ID),
        )
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=thread_registry,
        pool_submitter=lambda *_args, **_kwargs: None,
    )

    def pool_submitter(node, _step, **_kwargs) -> None:
        nonlocal submit_calls
        submit_calls += 1
        assert not orchestrator._lock.locked()  # noqa: SLF001 -- lock-order contract

    orchestrator._pool_submitter = pool_submitter  # noqa: SLF001

    root_scope = _compute_scope(ROOT_ID, export_scope)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))
    assert submit_calls >= 1


def test_inline_job_wire_builder_never_runs_while_orchestrator_lock_is_held(sample_turn):
    """Inline builders must not run under the orch lock (deadlock with scheduler→orch)."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    builder_saw_lock_held = False
    orchestrator_holder: dict[str, ComputeOrchestrator] = {}

    def build_wire(scope, **_kwargs):
        nonlocal builder_saw_lock_held
        orch = orchestrator_holder["orch"]
        builder_saw_lock_held = orch._lock.locked()  # noqa: SLF001
        return {"scope": scope.analytic_id}

    registry = build_compute_registry(
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
                build_step_job_wires=(("materialize", build_wire),),
                run_steps=(
                    (
                        "materialize",
                        lambda job: {"result": job["scope"]},
                    ),
                ),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=registry,
        pool_submitter=lambda *_args, **_kwargs: None,
    )
    orchestrator_holder["orch"] = orchestrator
    scope = _compute_scope(SHARED_ID, export_scope)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    assert orchestrator.nodes[scope].state == "complete"
    assert builder_saw_lock_held is False


def test_persist_never_runs_while_orchestrator_lock_is_held(sample_turn):
    """Fleet-style persist must not nest under the orch lock (deadlock with scheduler→orch)."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    persist_saw_lock_held = False
    orchestrator_holder: dict[str, ComputeOrchestrator] = {}

    class _LockCheckingPersistence(_StubPersistencePolicy):
        def persist(self, _ctx, scope, result_wire):
            nonlocal persist_saw_lock_held
            orch = orchestrator_holder["orch"]
            persist_saw_lock_held = orch._lock.locked()  # noqa: SLF001
            return None

    registry = build_compute_registry(
        (
            _outcome_compute_registration(
                SHARED_ID,
                outcome="persist",
                persistence_policy=_LockCheckingPersistence(),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(compute_registry=registry)
    orchestrator_holder["orch"] = orchestrator
    scope = _compute_scope(SHARED_ID, export_scope)
    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    assert handle.state == "complete"
    assert persist_saw_lock_held is False


def test_pool_persist_failure_must_not_leave_node_running(sample_turn):
    """Persist runs after step-complete success; a raise must not ghost-leave running.

    Observed fingerprint: completion history records pool success, in-flight/pool are
    empty, but the DAG node stays ``running`` so freeze single-step reports
    ``nothing_steppable`` and scores never emits row-complete.
    """
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    persist_error = RuntimeError("persist failed")

    class _RaisingPersistence(_StubPersistencePolicy):
        def persist(self, _ctx, scope, result_wire):
            del scope, result_wire
            raise persist_error

    def run_tier_solve(_job):
        return StepResult(outcome="persist", payload={"result": SHARED_ID})

    registry = build_compute_registry(
        (
            TurnAnalyticRegistration(
                catalog_entry=_catalog_entry(SHARED_ID),
                compute=lambda _ctx: {"analyticId": SHARED_ID},
                export_catalog=empty_export_catalog_for(SHARED_ID),
                scope_key_spec=_ROW_SCOPE_KEY,
                compute_profile=AnalyticComputeProfile(
                    steps=(ComputeStepSpec(step_kind="tier_solve", backend="thread"),),
                ),
                persistence_policy=_RaisingPersistence(),
                build_step_job_wires=(
                    ("tier_solve", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
                ),
                run_steps=(("tier_solve", run_tier_solve),),
            ),
        )
    )
    pool_submissions: list[ComputeScope] = []

    def pool_submitter(node, _step) -> None:
        pool_submissions.append(node.scope)

    orchestrator = ComputeOrchestrator(
        compute_registry=registry,
        pool_submitter=pool_submitter,
    )
    scope = _compute_scope(SHARED_ID, export_scope)
    orchestrator.submit(
        ComputeRequest(
            ctx=ctx,
            scope=scope,
            step_kind="tier_solve",
            priority_band="stream_attached",
        )
    )
    assert pool_submissions == [scope]
    assert orchestrator.nodes[scope].state == "running"

    step_completions: list[str] = []

    def on_step_complete(_scope, _node, step_kind, _step_index, surface, terminal_state) -> None:
        step_completions.append(f"{surface}:{step_kind}:{terminal_state}")

    orchestrator.register_step_complete_listener(on_step_complete)

    orchestrator.complete_pool_step(
        scope,
        result_wire=StepResult(outcome="persist", payload={"result": SHARED_ID}),
    )

    # Step-complete success is recorded before persist; persist failure must fail the node.
    assert step_completions == ["pool:tier_solve:success"]
    assert orchestrator.nodes[scope].state != "running"
    assert orchestrator.nodes[scope].state == "failed"
    assert orchestrator.nodes[scope].error is persist_error


def test_persist_deferred_demotes_waiting_deps_and_force_freshes_dependency(sample_turn):
    """PersistDeferredError demotes to waiting_deps and force_freshes the dependency.

    Mirrors fleet open-evidence recovery without fleet/scores imports in the
    orchestrator: refuse persist → waiting_deps (not failed, not soft parked) →
    dependency force_fresh submitted → after dependency completes again,
    dependent is ready.
    """
    from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery

    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    recovery = PersistDependencyRecovery(
        dependency_scope=shared_scope,
        force_fresh=True,
        step_kind="materialize",
    )

    class _DeferredOncePersistence(_StubPersistencePolicy):
        def __init__(self) -> None:
            self.calls = 0

        def persist(self, _ctx, scope, result_wire):
            del scope, result_wire
            self.calls += 1
            if self.calls == 1:
                raise PersistDeferredError(
                    "dependency evidence still open",
                    recovery=recovery,
                )

    deferred_persistence = _DeferredOncePersistence()
    pool_submissions: list[tuple[str, str | None]] = []

    def pool_submitter(node, step) -> None:
        pool_submissions.append((node.scope.analytic_id, step.step_kind))

    registry = build_compute_registry(
        (
            _pool_compute_registration(SHARED_ID, backend="thread"),
            _pool_compute_registration(
                BRANCH_B_ID,
                backend="thread",
                persistence_policy=deferred_persistence,
            ),
        )
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=registry,
        pool_submitter=pool_submitter,
    )

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=branch_b_scope))
    assert pool_submissions == [(SHARED_ID, "materialize")]
    assert orchestrator.nodes[shared_scope].state == "running"
    assert orchestrator.nodes[branch_b_scope].state == "waiting_deps"

    orchestrator.complete_pool_step(
        shared_scope,
        result_wire={"result": SHARED_ID},
    )
    assert orchestrator.nodes[shared_scope].state == "complete"
    assert orchestrator.nodes[branch_b_scope].state == "running"
    assert pool_submissions == [
        (SHARED_ID, "materialize"),
        (BRANCH_B_ID, "materialize"),
    ]

    orchestrator.complete_pool_step(
        branch_b_scope,
        result_wire=StepResult(outcome="persist", payload={"result": BRANCH_B_ID}),
    )

    assert deferred_persistence.calls == 1
    assert orchestrator.nodes[branch_b_scope].state == "waiting_deps"
    assert orchestrator.nodes[branch_b_scope].error is None
    assert orchestrator.nodes[shared_scope].state == "running"
    assert pool_submissions == [
        (SHARED_ID, "materialize"),
        (BRANCH_B_ID, "materialize"),
        (SHARED_ID, "materialize"),
    ]
    assert orchestrator.metrics.epoch_discards == 1

    orchestrator.complete_pool_step(
        shared_scope,
        result_wire={"result": SHARED_ID},
    )
    assert orchestrator.nodes[shared_scope].state == "complete"
    assert orchestrator.nodes[branch_b_scope].state == "running"
    assert pool_submissions[-1] == (BRANCH_B_ID, "materialize")

    orchestrator.complete_pool_step(
        branch_b_scope,
        result_wire=StepResult(outcome="persist", payload={"result": BRANCH_B_ID}),
    )
    assert deferred_persistence.calls == 2
    assert orchestrator.nodes[branch_b_scope].state == "complete"
    assert orchestrator.nodes[branch_b_scope].error is None


def test_diagnostics_snapshot_captures_nodes_and_ready_under_one_lock(sample_turn):
    """Diagnostics must read nodes and ready queue atomically, not via live mappings."""
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
        compute_registry=thread_registry,
        pool_submitter=pool_submitter,
    )
    orchestrator.register_dispatch_gate(
        lambda node: node.scope.analytic_id != BRANCH_B_ID,
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    branch_c_scope = _compute_scope(BRANCH_C_ID, export_scope)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))
    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})

    view = orchestrator.diagnostics_snapshot()
    nodes_by_scope = {node.scope: node for node in view.nodes}
    assert set(nodes_by_scope) == {root_scope, shared_scope, branch_b_scope, branch_c_scope}
    assert nodes_by_scope[shared_scope].state == "complete"
    assert nodes_by_scope[branch_c_scope].state == "running"
    assert nodes_by_scope[branch_b_scope].state == "ready"
    assert view.ready_scopes == (branch_b_scope,)
    # Snapshot is a frozen copy; mutating live state must not rewrite the view.
    orchestrator.nodes[branch_b_scope].state = "running"
    assert nodes_by_scope[branch_b_scope].state == "ready"


def test_dispatch_ready_work_releases_continuation_after_gate_clears(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    pool_submissions: list[ComputeScope] = []
    is_paused = False

    def pool_submitter(node, _step) -> None:
        pool_submissions.append(node.scope)

    compute_registry = build_compute_registry(
        (_pool_compute_registration(SHARED_ID, backend="thread"),)
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    unregister_pause = orchestrator.register_dispatch_gate(lambda _node: not is_paused)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    is_paused = True
    orchestrator.complete_pool_step(shared_scope, result_wire=StepResult(outcome="continue"))

    assert pool_submissions == [shared_scope]
    assert orchestrator.nodes[shared_scope].state == "ready"
    assert orchestrator.ready_scopes() == (shared_scope,)

    is_paused = False
    orchestrator.dispatch_ready_work()

    assert pool_submissions == [shared_scope, shared_scope]
    assert orchestrator.nodes[shared_scope].state == "running"
    unregister_pause()


def test_continue_payload_kept_when_terminal_complete_has_no_payload(sample_turn):
    """Provisional continue payload must remain the dependency result_wire.

    Scores materialize→continue→tier_solve skip previously left ``result_wire`` None,
    so fleet dispatch raised ``complete without a result wire``.
    """
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    calls = {"materialize": 0, "tier": 0}

    def run_materialize(_job):
        calls["materialize"] += 1
        return StepResult(outcome="continue", payload={"exportTree": {"ok": True}})

    def run_tier(_job):
        calls["tier"] += 1
        return StepResult(outcome="complete")

    registration = TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(SHARED_ID),
        compute=lambda _ctx: {"analyticId": SHARED_ID},
        export_catalog=empty_export_catalog_for(SHARED_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(
                ComputeStepSpec(step_kind="materialize", backend="inline"),
                ComputeStepSpec(step_kind="tier_solve", backend="inline"),
            ),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
            ("tier_solve", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(
            ("materialize", run_materialize),
            ("tier_solve", run_tier),
        ),
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((registration,)),
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))

    assert calls == {"materialize": 1, "tier": 1}
    assert handle.state == "complete"
    assert handle.result_wire == {"exportTree": {"ok": True}}


def test_composed_dispatch_gates_and_together_and_unregister_is_selective(sample_turn):
    """Pause and freeze gates coexist; clearing one leaves the other."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    pool_submissions: list[str] = []
    pause_blocks = False
    freeze_blocks_branch_b = False

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
        compute_registry=thread_registry,
        pool_submitter=pool_submitter,
    )
    unregister_pause = orchestrator.register_dispatch_gate(lambda _node: not pause_blocks)
    unregister_freeze = orchestrator.register_dispatch_gate(
        lambda node: not (freeze_blocks_branch_b and node.scope.analytic_id == BRANCH_B_ID),
    )

    root_scope = _compute_scope(ROOT_ID, export_scope)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    branch_c_scope = _compute_scope(BRANCH_C_ID, export_scope)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope))
    assert pool_submissions == [SHARED_ID]

    pause_blocks = True
    freeze_blocks_branch_b = True
    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})

    assert pool_submissions == [SHARED_ID]
    assert orchestrator.nodes[branch_b_scope].state == "ready"
    assert orchestrator.nodes[branch_c_scope].state == "ready"
    assert set(orchestrator.ready_scopes()) == {branch_b_scope, branch_c_scope}

    # Clear pause only -- freeze still blocks branch B; branch C may run.
    pause_blocks = False
    unregister_pause()
    orchestrator.dispatch_ready_work()

    assert pool_submissions == [SHARED_ID, BRANCH_C_ID]
    assert orchestrator.nodes[branch_c_scope].state == "running"
    assert orchestrator.nodes[branch_b_scope].state == "ready"
    assert orchestrator.ready_scopes() == (branch_b_scope,)

    # Clear freeze -- branch B may run.
    unregister_freeze()
    orchestrator.dispatch_ready_work()

    assert pool_submissions == [SHARED_ID, BRANCH_C_ID, BRANCH_B_ID]
    assert orchestrator.nodes[branch_b_scope].state == "running"
