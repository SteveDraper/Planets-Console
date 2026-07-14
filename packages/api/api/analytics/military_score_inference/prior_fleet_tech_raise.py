"""Raise early tech bands from prior-turn fleet max tech (#227)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from api.analytics.fleet.max_tech import max_tech_in_turn_catalog
from api.analytics.military_score_inference.tier_policy import (
    FILTER_AXES,
    ComponentFilter,
    FilterAxis,
    InferenceCatalogFilters,
    InferenceTierPolicyStep,
)
from api.models.game import TurnInfo


@dataclass(frozen=True)
class PriorFleetTechRaisePlan:
    """Resolved tech-band raise (and optional skip) for one policy step."""

    policy_step: InferenceTierPolicyStep
    skipped: bool
    axes: tuple[dict[str, object], ...]

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "priorFleetTechRaise": {
                "skippedDueToPriorFleetTechSaturation": self.skipped,
                "axes": list(self.axes),
            }
        }


def _configured_max_tech(component_filter: ComponentFilter) -> int | None:
    if component_filter.all or not component_filter.tech_levels:
        return None
    return max(component_filter.tech_levels)


def _raised_tech_levels(effective_max: int) -> tuple[int, ...]:
    return tuple(range(1, effective_max + 1))


def _axis_raise_record(
    axis: FilterAxis,
    component_filter: ComponentFilter,
    *,
    observed_max: int | None,
    catalog_max: int | None,
) -> tuple[ComponentFilter, dict[str, object], bool]:
    """Return (possibly raised filter, diagnostics row, saturated?)."""
    configured_max = _configured_max_tech(component_filter)
    if configured_max is None:
        raise ValueError(
            f"raiseMaxTechFromPriorFleet on {axis} requires a non-empty techLevels band"
        )
    effective_max = configured_max
    if observed_max is not None and observed_max > effective_max:
        effective_max = observed_max
    raised_filter = replace(
        component_filter,
        tech_levels=_raised_tech_levels(effective_max),
    )
    saturated = catalog_max is not None and effective_max >= catalog_max
    return (
        raised_filter,
        {
            "axis": axis,
            "configuredMaxTech": configured_max,
            "observedMaxTech": observed_max,
            "effectiveMaxTech": effective_max,
            "catalogMaxTech": catalog_max,
            "saturated": saturated,
        },
        saturated,
    )


def resolve_prior_fleet_tech_raise_plan(
    policy_step: InferenceTierPolicyStep,
    *,
    turn: TurnInfo,
    prior_fleet_max_tech_by_axis: Mapping[str, int] | None,
) -> PriorFleetTechRaisePlan | None:
    """Apply ``raiseMaxTechFromPriorFleet``; return None when the step has no flagged axes.

    When every flagged axis is already at (or above) turn-catalog max after raising,
    and the step has no ``all: true`` axis (those still need a solve to widen),
    ``skipped`` is True and the ladder should omit the step without solving.
    """
    flagged: list[FilterAxis] = [
        axis
        for axis in FILTER_AXES
        if policy_step.filters.axis_filter(axis).raise_max_tech_from_prior_fleet
    ]
    if not flagged:
        return None

    observed = prior_fleet_max_tech_by_axis
    observed_map = observed or {}
    raised_by_axis: dict[str, ComponentFilter] = {}
    axis_rows: list[dict[str, object]] = []
    saturated_flags: list[bool] = []
    for axis in flagged:
        component_filter = policy_step.filters.axis_filter(axis)
        raised_filter, row, saturated = _axis_raise_record(
            axis,
            component_filter,
            observed_max=observed_map.get(axis),
            catalog_max=max_tech_in_turn_catalog(turn, axis),
        )
        raised_by_axis[axis] = raised_filter
        axis_rows.append(row)
        saturated_flags.append(saturated)

    filters = InferenceCatalogFilters(
        hulls=raised_by_axis.get("hulls", policy_step.filters.hulls),
        engines=raised_by_axis.get("engines", policy_step.filters.engines),
        beams=raised_by_axis.get("beams", policy_step.filters.beams),
        launchers=raised_by_axis.get("launchers", policy_step.filters.launchers),
    )
    has_hulls_all = policy_step.filters.hulls.all
    # Only omit steps when prior-fleet input was applied. Pending/unavailable keep
    # YAML constants and still solve (sample catalogs may have max tech below the
    # configured band; skipping those would drop early tiers incorrectly).
    fleet_applied = prior_fleet_max_tech_by_axis is not None
    return PriorFleetTechRaisePlan(
        policy_step=replace(policy_step, filters=filters),
        # Do not skip steps that open hulls to ``all`` (e.g. widen_hulls); saturation
        # only omits pure tech-band constrained steps.
        skipped=fleet_applied and all(saturated_flags) and not has_hulls_all,
        axes=tuple(axis_rows),
    )
