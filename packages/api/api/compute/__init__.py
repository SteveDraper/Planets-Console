"""Compute orchestrator foundation types and registry."""

from api.compute.persistence import PersistencePolicy
from api.compute.profile import (
    VALID_COMPUTE_BACKENDS,
    AnalyticComputeProfile,
    ComputeBackend,
    ComputeStepSpec,
)
from api.compute.scope import (
    WILDCARD,
    ComputeScope,
    ScopeAxis,
    ScopeKeySpec,
    compute_scope_to_export_scope,
    fingerprint_parameters,
    normalize_export_scope_to_compute_scope,
)
from api.compute.wire import BuildStepJobWireFn, DependencyOutputs, RunStepFn

_REGISTRY_EXPORTS = frozenset(
    {
        "COMPUTE_REGISTRY",
        "AnalyticComputeRegistration",
        "build_compute_registry",
        "validate_turn_analytic_compute_registration",
    }
)


_COMPUTE_ORCHESTRATOR_EXPORTS = frozenset(
    {
        "ComputeHandle",
        "ComputeNodeRun",
        "ComputeOrchestrator",
        "ComputeRequest",
        "NodeState",
        "OrchestratorMetrics",
        "PoolSubmitter",
    }
)

_DAG_EXPORTS = frozenset(
    {
        "PlannedComputeNode",
        "plan_compute_dag",
    }
)


def __getattr__(name: str) -> object:
    if name in _REGISTRY_EXPORTS:
        from api.compute import registry as registry_module

        return getattr(registry_module, name)
    if name in _COMPUTE_ORCHESTRATOR_EXPORTS:
        from api.compute import orchestrator as orchestrator_module

        return getattr(orchestrator_module, name)
    if name in _DAG_EXPORTS:
        from api.compute import dag as dag_module

        return getattr(dag_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "COMPUTE_REGISTRY",
    "WILDCARD",
    "VALID_COMPUTE_BACKENDS",
    "AnalyticComputeProfile",
    "AnalyticComputeRegistration",
    "BuildStepJobWireFn",
    "ComputeBackend",
    "ComputeHandle",
    "ComputeNodeRun",
    "ComputeOrchestrator",
    "ComputeRequest",
    "ComputeScope",
    "ComputeStepSpec",
    "DependencyOutputs",
    "NodeState",
    "OrchestratorMetrics",
    "PersistencePolicy",
    "PlannedComputeNode",
    "PoolSubmitter",
    "RunStepFn",
    "ScopeAxis",
    "ScopeKeySpec",
    "build_compute_registry",
    "compute_scope_to_export_scope",
    "fingerprint_parameters",
    "normalize_export_scope_to_compute_scope",
    "plan_compute_dag",
    "validate_turn_analytic_compute_registration",
]
