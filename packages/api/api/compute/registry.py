"""Compute orchestrator registry built from turn analytic registrations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from api.analytics.registration import TurnAnalyticRegistration
from api.compute.persistence import PersistencePolicy
from api.compute.profile import VALID_COMPUTE_BACKENDS, AnalyticComputeProfile, ComputeStepSpec
from api.compute.scope import ScopeKeySpec
from api.compute.wire import BuildStepJobWireFn, RunStepFn
from api.validation import require_non_empty_string


@dataclass(frozen=True)
class AnalyticComputeRegistration:
    """Validated compute orchestrator surface for one turn analytic."""

    analytic_id: str
    scope_key_spec: ScopeKeySpec
    compute_profile: AnalyticComputeProfile
    persistence_policy: PersistencePolicy
    build_step_job_wire: Mapping[str, BuildStepJobWireFn]
    run_step: Mapping[str, RunStepFn]


def _mapping_from_pairs(
    pairs: tuple[tuple[str, object], ...],
    *,
    analytic_id: str,
    field: str,
) -> dict[str, object]:
    mapped: dict[str, object] = {}
    for key, value in pairs:
        require_non_empty_string(key, field=field, analytic_id=analytic_id, subject="compute")
        if key in mapped:
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} duplicate {field} step_kind: {key!r}"
            )
        mapped[key] = value
    return mapped


def _check_persistence_policy(policy: object, *, analytic_id: str) -> None:
    for hook in (
        "is_satisfied",
        "satisfied_result_wire",
        "persist",
        "invalidate",
        "invalidation_generation",
    ):
        if not callable(getattr(policy, hook, None)):
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} persistence_policy must implement "
                f"callable {hook!r}, got {type(policy).__name__}"
            )


def _validate_compute_step_spec(step: ComputeStepSpec, *, analytic_id: str) -> None:
    require_non_empty_string(
        step.step_kind, field="step_kind", analytic_id=analytic_id, subject="compute"
    )
    if step.backend not in VALID_COMPUTE_BACKENDS:
        raise RuntimeError(
            f"Turn analytic {analytic_id!r} compute step {step.step_kind!r} has unknown "
            f"backend {step.backend!r}; expected one of "
            f"{sorted(VALID_COMPUTE_BACKENDS)!r}"
        )


def validate_turn_analytic_compute_registration(
    registration: TurnAnalyticRegistration,
) -> AnalyticComputeRegistration | None:
    """Validate one registration's compute surface; return None when compute is not configured."""
    analytic_id = registration.catalog_entry.id
    compute_profile = registration.compute_profile
    if compute_profile is None:
        return None

    scope_key_spec = registration.scope_key_spec
    if scope_key_spec is None:
        raise RuntimeError(
            f"Turn analytic {analytic_id!r} sets compute_profile but not scope_key_spec"
        )
    if not scope_key_spec.axes and not scope_key_spec.parameter_fields:
        raise RuntimeError(
            f"Turn analytic {analytic_id!r} scope_key_spec must declare at least one axis "
            f"or parameter field"
        )

    persistence_policy = registration.persistence_policy
    if persistence_policy is None:
        raise RuntimeError(
            f"Turn analytic {analytic_id!r} sets compute_profile but not persistence_policy"
        )
    _check_persistence_policy(persistence_policy, analytic_id=analytic_id)

    if not compute_profile.steps:
        raise RuntimeError(f"Turn analytic {analytic_id!r} compute_profile.steps must not be empty")

    step_kinds: list[str] = []
    for step in compute_profile.steps:
        _validate_compute_step_spec(step, analytic_id=analytic_id)
        if step.step_kind in step_kinds:
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} duplicate compute step_kind: {step.step_kind!r}"
            )
        step_kinds.append(step.step_kind)
    declared_step_kinds = frozenset(step_kinds)

    build_step_job_wire = _mapping_from_pairs(
        registration.build_step_job_wires,
        analytic_id=analytic_id,
        field="build_step_job_wires",
    )
    run_step = _mapping_from_pairs(
        registration.run_steps,
        analytic_id=analytic_id,
        field="run_steps",
    )

    for step_kind in declared_step_kinds:
        builder = build_step_job_wire.get(step_kind)
        if not callable(builder):
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} missing build_step_job_wire for "
                f"step_kind {step_kind!r}"
            )
        runner = run_step.get(step_kind)
        if not callable(runner):
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} missing run_step for step_kind {step_kind!r}"
            )

    unknown_builders = sorted(set(build_step_job_wire) - declared_step_kinds)
    if unknown_builders:
        raise RuntimeError(
            f"Turn analytic {analytic_id!r} unknown build_step_job_wire step_kind(s): "
            f"{unknown_builders!r}"
        )
    unknown_runners = sorted(set(run_step) - declared_step_kinds)
    if unknown_runners:
        raise RuntimeError(
            f"Turn analytic {analytic_id!r} unknown run_step step_kind(s): {unknown_runners!r}"
        )

    return AnalyticComputeRegistration(
        analytic_id=analytic_id,
        scope_key_spec=scope_key_spec,
        compute_profile=compute_profile,
        persistence_policy=persistence_policy,
        build_step_job_wire=build_step_job_wire,
        run_step=run_step,
    )


def build_compute_registry(
    registrations: tuple[TurnAnalyticRegistration, ...],
) -> dict[str, AnalyticComputeRegistration]:
    """Build and validate the compute registry from turn analytic registrations."""
    registry: dict[str, AnalyticComputeRegistration] = {}
    for registration in registrations:
        compute_registration = validate_turn_analytic_compute_registration(registration)
        if compute_registration is None:
            continue
        analytic_id = compute_registration.analytic_id
        if analytic_id in registry:
            raise RuntimeError(f"Duplicate compute registration id: {analytic_id!r}")
        registry[analytic_id] = compute_registration
    return registry


def _production_compute_registrations() -> tuple[TurnAnalyticRegistration, ...]:
    from api.analytics.registry import TURN_ANALYTIC_REGISTRATIONS

    return TURN_ANALYTIC_REGISTRATIONS


_COMPUTE_REGISTRY: dict[str, AnalyticComputeRegistration] | None = None


def __getattr__(name: str) -> object:
    global _COMPUTE_REGISTRY
    if name == "COMPUTE_REGISTRY":
        if _COMPUTE_REGISTRY is None:
            _COMPUTE_REGISTRY = build_compute_registry(_production_compute_registrations())
        return _COMPUTE_REGISTRY
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
