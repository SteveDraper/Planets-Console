"""Drive a persist-deferred recovery on the diamond export fixture, step by step.

ROOT ensures BRANCH_B and BRANCH_C, and each branch ensures SHARED. Pool steps
are held, so a test finishes each step itself and nothing refreshes readiness
behind its back.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.registration import (
    TurnAnalyticRegistration,
    resolve_registration_export_catalog,
)
from api.compute import (
    ComputeHandle,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    build_compute_registry,
)
from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery
from api.compute.step_execution_key import ExecutionRef
from api.compute.wire import StepResult

from tests.compute_orchestrator_fixtures import (
    ArmableRootPlanHook,
    RecordingPersistencePolicy,
    inline_compute_registration,
    make_compute_scope,
    make_export_scope,
    pool_compute_registration,
)
from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fixtures.export_framework.diamond_exports import (
    BRANCH_B_ID,
    BRANCH_C_ID,
    ROOT_ID,
    SHARED_ID,
)
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)


class DeferringPersistencePolicy(RecordingPersistencePolicy):
    """Records persists, or raises ``PersistDeferredError`` with ``recovery`` once set."""

    def __init__(self) -> None:
        super().__init__()
        self.recovery: PersistDependencyRecovery | None = None

    def persist(self, ctx, scope, result_wire) -> None:
        if self.recovery is not None:
            raise PersistDeferredError("dependency must re-close", recovery=self.recovery)
        super().persist(ctx, scope, result_wire)


@dataclass(frozen=True)
class RunningBranch:
    """BRANCH_B running on a complete SHARED, with ROOT waiting on it.

    ``shared_root_plan`` is SHARED's root plan hook; arm it to act inside the
    next SHARED-rooted submission.
    """

    orchestrator: ComputeOrchestrator
    ctx: AnalyticQueryContext
    shared: ComputeScope
    branch: ComputeScope
    root: ComputeScope
    branch_policy: DeferringPersistencePolicy
    branch_waiter: ComputeHandle
    shared_root_plan: ArmableRootPlanHook


def _hold_pool_steps(node, step, **_kwargs) -> None:
    del node, step


def running_branch(
    sample_turn, *, extra_registrations: tuple[TurnAnalyticRegistration, ...] = ()
) -> RunningBranch:
    """Set up the diamond, plus ``extra_registrations`` in both registries."""
    export_registry = {
        **DIAMOND_FIXTURE_EXPORT_REGISTRY,
        **{
            registration.catalog_entry.id: resolve_registration_export_catalog(registration)
            for registration in extra_registrations
        },
    }
    ctx = make_fixture_query_context(sample_turn, registry=export_registry)
    export_scope = make_export_scope(sample_turn)
    branch_policy = DeferringPersistencePolicy()
    shared_root_plan = ArmableRootPlanHook()
    registry = build_compute_registry(
        (
            replace(
                pool_compute_registration(
                    SHARED_ID, backend="thread", persistence_policy=RecordingPersistencePolicy()
                ),
                open_root_plan=shared_root_plan,
            ),
            pool_compute_registration(
                BRANCH_B_ID, backend="thread", persistence_policy=branch_policy
            ),
            inline_compute_registration(BRANCH_C_ID),
            pool_compute_registration(
                ROOT_ID, backend="thread", persistence_policy=RecordingPersistencePolicy()
            ),
            *extra_registrations,
        )
    )
    orchestrator = ComputeOrchestrator(compute_registry=registry, pool_submitter=_hold_pool_steps)
    shared = make_compute_scope(SHARED_ID, export_scope)
    branch = make_compute_scope(BRANCH_B_ID, export_scope)
    root = make_compute_scope(ROOT_ID, export_scope)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root))
    complete_running_pool_step(orchestrator, shared, result_wire={"result": SHARED_ID})
    assert orchestrator.nodes[branch].state == "running"
    assert orchestrator.nodes[root].state == "waiting_deps"
    branch_waiter = orchestrator.submit(ComputeRequest(ctx=ctx, scope=branch))
    assert branch_waiter.is_waiter

    return RunningBranch(
        orchestrator=orchestrator,
        ctx=ctx,
        shared=shared,
        branch=branch,
        root=root,
        branch_policy=branch_policy,
        branch_waiter=branch_waiter,
        shared_root_plan=shared_root_plan,
    )


def persist_branch_step_deferred(setup: RunningBranch, recovery: PersistDependencyRecovery) -> None:
    setup.branch_policy.recovery = recovery
    complete_running_pool_step(
        setup.orchestrator,
        setup.branch,
        result_wire=StepResult(outcome="persist", payload={"result": BRANCH_B_ID}),
    )


def shared_recovery(setup: RunningBranch) -> PersistDependencyRecovery:
    return PersistDependencyRecovery(dependency_scope=setup.shared, step_kind="materialize")


def branch_superseded_execution(setup: RunningBranch) -> ExecutionRef | None:
    """The ``superseded`` execution of the branch's recorded persist deferral."""
    deferral = setup.orchestrator.nodes[setup.branch].last_persist_deferral
    assert deferral is not None
    return deferral.superseded
