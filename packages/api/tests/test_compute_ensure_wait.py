"""Tests for ComputeHandle.wait and orchestrator ensure_scope (#204 phase 1)."""

from __future__ import annotations

import threading
import time

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
    ComputeWaitTimeoutError,
    ScopeKeySpec,
    build_compute_registry,
    normalize_export_scope_to_compute_scope,
)

from tests.fixtures.export_framework.diamond_exports import SHARED_ID
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


def _thread_registration(
    analytic_id: str,
    *,
    persistence_policy: object | None = None,
) -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(analytic_id),
        compute=lambda _ctx: {"analyticId": analytic_id},
        export_catalog=empty_export_catalog_for(analytic_id),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="thread"),),
        ),
        persistence_policy=persistence_policy or _StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", lambda job: {"result": job["scope"]}),),
    )


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


def test_handle_wait_returns_when_pool_step_completes(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((_thread_registration(SHARED_ID),)),
        pool_submitter=lambda _node, _step: None,
    )

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    assert handle.state == "running"

    done = threading.Event()
    errors: list[BaseException] = []

    def wait_for_complete() -> None:
        try:
            handle.wait(timeout=2.0)
            done.set()
        except BaseException as exc:
            errors.append(exc)
            done.set()

    waiter = threading.Thread(target=wait_for_complete, daemon=True)
    waiter.start()
    time.sleep(0.05)
    assert not done.is_set()

    orchestrator.complete_pool_step(
        shared_scope,
        result_wire={"result": SHARED_ID},
    )
    assert done.wait(timeout=2.0)
    assert errors == []
    assert handle.state == "complete"
    waiter.join(timeout=1.0)


def test_handle_wait_timeout_fails_waiter_only(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((_thread_registration(SHARED_ID),)),
        pool_submitter=lambda _node, _step: None,
    )

    leader = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    waiter = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    assert leader.state == "running"
    assert waiter.state == "attach_inflight"

    with pytest.raises(ComputeWaitTimeoutError) as raised:
        waiter.wait(timeout=0.05)

    assert raised.value.scope == shared_scope
    assert raised.value.timeout_sec == 0.05
    # DAG work is still in flight for attach / retry / streams (T1).
    assert orchestrator.nodes[shared_scope].state == "running"
    assert leader.state == "running"
    assert leader.error is None


def test_handle_wait_raises_node_failure(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    pool_failure = RuntimeError("pool step failed")
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((_thread_registration(SHARED_ID),)),
        pool_submitter=lambda _node, _step: None,
    )

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    errors: list[BaseException] = []
    done = threading.Event()

    def wait_for_failure() -> None:
        try:
            handle.wait(timeout=2.0)
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=wait_for_failure, daemon=True)
    thread.start()
    time.sleep(0.05)
    orchestrator.complete_pool_step(shared_scope, error=pool_failure)
    assert done.wait(timeout=2.0)
    assert errors == [pool_failure]
    thread.join(timeout=1.0)


class _SatisfiedPersistencePolicy(_StubPersistencePolicy):
    def is_satisfied(self, _ctx, _scope) -> bool:
        return True

    def satisfied_result_wire(self, _ctx, _scope) -> dict:
        return {"satisfied": True}


def test_ensure_scope_short_circuits_when_already_satisfied(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    policy = _SatisfiedPersistencePolicy()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (_thread_registration(SHARED_ID, persistence_policy=policy),)
        ),
        pool_submitter=lambda _node, _step: None,
    )

    handle = orchestrator.ensure_scope(
        ComputeRequest(ctx=ctx, scope=shared_scope, priority_band="interactive_ensure"),
        timeout=1.0,
    )

    assert handle.state == "complete"
    assert handle.result_wire == {"satisfied": True}
    assert orchestrator.metrics.satisfaction_short_circuits == 1
    # Never handed to the pool when durable satisfaction already holds.
    assert orchestrator.nodes[shared_scope].state == "complete"


def test_ensure_scope_rebuilds_hollow_terminal_without_force_fresh(sample_turn):
    """Hollow complete after wipe: default ensure (F1 force_fresh=False) rebuilds.

    Durable satisfaction fails while a stale terminal remains. Ensure drops that
    hollow cache hit, then submits with the caller's force_fresh (False) -- it
    must not silently set force_fresh=True.
    """
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    policy = _StubPersistencePolicy()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (_thread_registration(SHARED_ID, persistence_policy=policy),)
        ),
        pool_submitter=lambda _node, _step: None,
    )

    # Seed a terminal node as if a prior ensure completed, then durable state wiped.
    first = orchestrator.submit(
        ComputeRequest(ctx=ctx, scope=shared_scope, priority_band="interactive_ensure"),
    )
    orchestrator.complete_pool_step(shared_scope, result_wire={"result": "stale"})
    assert first.wait(timeout=1.0).state == "complete"
    prior_generation = orchestrator.nodes[shared_scope].execution_generation

    result_box: list[object] = []
    errors: list[BaseException] = []
    started = threading.Event()

    def ensure_in_background() -> None:
        started.set()
        try:
            result_box.append(
                orchestrator.ensure_scope(
                    ComputeRequest(
                        ctx=ctx,
                        scope=shared_scope,
                        priority_band="interactive_ensure",
                        force_fresh=False,
                    ),
                    timeout=2.0,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=ensure_in_background, daemon=True)
    thread.start()
    assert started.wait(timeout=1.0)
    time.sleep(0.05)
    rebuilt = orchestrator.nodes[shared_scope]
    assert rebuilt.state == "running"
    assert rebuilt.execution_generation != prior_generation

    orchestrator.complete_pool_step(shared_scope, result_wire={"result": "fresh"})
    thread.join(timeout=2.0)
    assert errors == []
    assert len(result_box) == 1
    assert result_box[0].state == "complete"
    assert result_box[0].result_wire == {"result": "fresh"}


def test_ensure_scope_rebuilds_hollow_dependency_terminals(sample_turn):
    """Hollow complete deps must rebuild with the ensure root after durable wipe.

    Root-only hollow eviction left planned dependency scopes ``complete`` in the
    DAG; ``_register_planned_node`` skipped them and the root ran against empty
    durable state. Drop unsatisfied terminals for every planned scope.
    """
    from api.compute.wire import StepResult

    from tests.fixtures.export_framework.diamond_exports import (
        BRANCH_B_EXPORT_CATALOG,
        BRANCH_B_ID,
        SHARED_EXPORT_CATALOG,
        SHARED_ID,
    )

    def _inline_registration(
        analytic_id: str,
        export_catalog: object,
        *,
        persistence_policy: object,
    ) -> TurnAnalyticRegistration:
        def run_materialize(_job: object) -> StepResult:
            return StepResult(outcome="complete", payload={"result": analytic_id})

        return TurnAnalyticRegistration(
            catalog_entry=_catalog_entry(analytic_id),
            compute=lambda _ctx: {"analyticId": analytic_id},
            export_catalog=export_catalog,
            scope_key_spec=_ROW_SCOPE_KEY,
            compute_profile=AnalyticComputeProfile(
                steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
            ),
            persistence_policy=persistence_policy,
            build_step_job_wires=(
                ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
            ),
            run_steps=(("materialize", run_materialize),),
        )

    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_scope = _compute_scope(BRANCH_B_ID, export_scope)
    policy = _StubPersistencePolicy()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (
                _inline_registration(SHARED_ID, SHARED_EXPORT_CATALOG, persistence_policy=policy),
                _inline_registration(
                    BRANCH_B_ID, BRANCH_B_EXPORT_CATALOG, persistence_policy=policy
                ),
            )
        ),
        pool_submitter=lambda _node, _step: None,
    )

    first = orchestrator.ensure_scope(
        ComputeRequest(ctx=ctx, scope=branch_scope, priority_band="interactive_ensure"),
        timeout=2.0,
    )
    assert first.state == "complete"
    assert orchestrator.nodes[shared_scope].state == "complete"
    prior_shared_generation = orchestrator.nodes[shared_scope].execution_generation

    second = orchestrator.ensure_scope(
        ComputeRequest(
            ctx=ctx,
            scope=branch_scope,
            priority_band="interactive_ensure",
            force_fresh=False,
        ),
        timeout=2.0,
    )
    assert second.state == "complete"
    rebuilt_shared = orchestrator.nodes[shared_scope]
    assert rebuilt_shared.state == "complete"
    assert rebuilt_shared.execution_generation != prior_shared_generation


def test_ensure_scope_submit_and_wait_until_complete(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((_thread_registration(SHARED_ID),)),
        pool_submitter=lambda _node, _step: None,
    )

    result_box: list[object] = []
    errors: list[BaseException] = []
    started = threading.Event()

    def ensure_in_background() -> None:
        started.set()
        try:
            handle = orchestrator.ensure_scope(
                ComputeRequest(
                    ctx=ctx,
                    scope=shared_scope,
                    priority_band="interactive_ensure",
                ),
                timeout=2.0,
            )
            result_box.append(handle)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=ensure_in_background, daemon=True)
    thread.start()
    assert started.wait(timeout=1.0)
    time.sleep(0.05)
    assert orchestrator.nodes[shared_scope].state == "running"

    orchestrator.complete_pool_step(
        shared_scope,
        result_wire={"result": SHARED_ID},
    )
    thread.join(timeout=2.0)
    assert errors == []
    assert len(result_box) == 1
    assert result_box[0].state == "complete"


def test_ensure_scope_timeout_leaves_inflight_running(sample_turn):
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((_thread_registration(SHARED_ID),)),
        pool_submitter=lambda _node, _step: None,
    )

    with pytest.raises(ComputeWaitTimeoutError):
        orchestrator.ensure_scope(
            ComputeRequest(ctx=ctx, scope=shared_scope),
            timeout=0.05,
        )

    assert orchestrator.nodes[shared_scope].state == "running"

    # Later attach can still complete the shared in-flight work.
    late = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    assert late.state == "attach_inflight"
    orchestrator.complete_pool_step(
        shared_scope,
        result_wire={"result": SHARED_ID},
    )
    assert late.wait(timeout=1.0).state == "complete"
