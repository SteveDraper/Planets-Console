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
    fingerprint_parameters,
    normalize_export_scope_to_compute_scope,
)
from api.compute.wire import BuildStepJobWireFn, RunStepFn

_REGISTRY_EXPORTS = frozenset(
    {
        "COMPUTE_REGISTRY",
        "AnalyticComputeRegistration",
        "build_compute_registry",
        "validate_turn_analytic_compute_registration",
    }
)


def __getattr__(name: str) -> object:
    if name in _REGISTRY_EXPORTS:
        from api.compute import registry as registry_module

        return getattr(registry_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "COMPUTE_REGISTRY",
    "WILDCARD",
    "VALID_COMPUTE_BACKENDS",
    "AnalyticComputeProfile",
    "AnalyticComputeRegistration",
    "BuildStepJobWireFn",
    "ComputeBackend",
    "ComputeScope",
    "ComputeStepSpec",
    "PersistencePolicy",
    "RunStepFn",
    "ScopeAxis",
    "ScopeKeySpec",
    "build_compute_registry",
    "fingerprint_parameters",
    "normalize_export_scope_to_compute_scope",
    "validate_turn_analytic_compute_registration",
]
