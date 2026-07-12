"""Resolve compute-profile steps for diagnostics views and gates."""

from __future__ import annotations

from api.compute.profile import ComputeStepSpec
from api.compute.registry import COMPUTE_REGISTRY


def profile_step_at(analytic_id: str, profile_step_index: int) -> ComputeStepSpec | None:
    """Return the profile step at ``profile_step_index``, or ``None`` if unresolved."""
    registration = COMPUTE_REGISTRY.get(analytic_id)
    if registration is None:
        return None
    steps = registration.compute_profile.steps
    if profile_step_index < 0 or profile_step_index >= len(steps):
        return None
    return steps[profile_step_index]


def registration_step_kind(analytic_id: str, profile_step_index: int) -> str | None:
    """Return the registered ``step_kind`` for a node profile index, if any."""
    step = profile_step_at(analytic_id, profile_step_index)
    return None if step is None else step.step_kind


def profile_step_is_inline(analytic_id: str, profile_step_index: int) -> bool:
    """Return whether the profile step at ``profile_step_index`` uses the inline backend."""
    step = profile_step_at(analytic_id, profile_step_index)
    return step is not None and step.backend == "inline"
