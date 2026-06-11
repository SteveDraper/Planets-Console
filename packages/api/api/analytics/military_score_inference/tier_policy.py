"""YAML inference search tier policy load, validation, and optional overlay hook."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from api.analytics.military_score_inference.aggregate_action_registry import (
    aggregate_allowlist_key,
)
from api.analytics.scores_assets import Scores

SlotCountMode = Literal["none", "partial"]
FilterAxis = Literal["hulls", "engines", "beams", "launchers"]
FILTER_AXES: tuple[FilterAxis, ...] = ("hulls", "engines", "beams", "launchers")

DEFAULT_MAX_SEEDS = 5

# ``all: true`` widens eligibility on that axis. It does **not** mean "every component id
# in the turn catalog regardless of player state."
#
# - hulls: all buildable hull ids for the player (turn.racehulls ∩ turn hull catalog),
#   with no additional tech-level band.
# - engines / beams / launchers: player active* list intersect turn catalog; when the active
#   list is empty, jump to the full turn catalog for that axis (existing Planets.nu rule).
#
# ``techLevels: [...]`` narrows to components whose ``techlevel`` is in the list. Hull tech
# bands apply on top of the buildable-hull set; other axes filter the turn catalog directly.


@dataclass(frozen=True)
class ComponentFilter:
    """Catalog filter for one ship-build component axis.

    Exactly one primary mode: ``all=True`` (widened) or non-empty ``tech_levels`` (tech band).
    Optional ``component_ids`` further restricts the resolved set (reserved for future overlay
    and policy refinement when multiple ids share a tech level).
    """

    all: bool = False
    tech_levels: tuple[int, ...] = ()
    component_ids: tuple[int, ...] = ()

    def to_snapshot(self) -> dict[str, object]:
        if self.all:
            snapshot: dict[str, object] = {"all": True}
        else:
            snapshot = {"techLevels": list(self.tech_levels)}
        if self.component_ids:
            snapshot["componentIds"] = list(self.component_ids)
        return snapshot


@dataclass(frozen=True)
class InferenceCatalogFilters:
    hulls: ComponentFilter
    engines: ComponentFilter
    beams: ComponentFilter
    launchers: ComponentFilter

    def to_snapshot(self) -> dict[str, object]:
        return {
            "hulls": self.hulls.to_snapshot(),
            "engines": self.engines.to_snapshot(),
            "beams": self.beams.to_snapshot(),
            "launchers": self.launchers.to_snapshot(),
        }

    def axis_filter(self, axis: FilterAxis) -> ComponentFilter:
        return getattr(self, axis)


@dataclass(frozen=True)
class ComponentFilterOverlay:
    """Per-axis overlay fragment merged at resolve time (#78)."""

    append_tech_levels: tuple[int, ...] = ()
    append_component_ids: tuple[int, ...] = ()
    force_all: bool = False


@dataclass(frozen=True)
class TierPolicyOverlay:
    """Runtime overlay merged into the static policy at resolve time (#78).

    #78 implements deterministic merge into ``InferenceCatalogFilters`` per step.
    When ``overlay`` is not ``None``, #77 passes the base YAML steps through unchanged.
    """

    hulls: ComponentFilterOverlay | None = None
    engines: ComponentFilterOverlay | None = None
    beams: ComponentFilterOverlay | None = None
    launchers: ComponentFilterOverlay | None = None
    aggregate_cap_bumps: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceTierPolicyStep:
    id: str
    filters: InferenceCatalogFilters
    beam_slot_counts: SlotCountMode
    launcher_slot_counts: SlotCountMode
    aggregate_allowlist: dict[str, int]
    alpha: int
    max_seeds: int = DEFAULT_MAX_SEEDS

    def constraint_snapshot(self) -> dict[str, object]:
        return {
            "id": self.id,
            "filters": self.filters.to_snapshot(),
            "beamSlotCounts": self.beam_slot_counts,
            "launcherSlotCounts": self.launcher_slot_counts,
            "aggregateAllowlist": dict(self.aggregate_allowlist),
            "alpha": self.alpha,
            "maxSeeds": self.max_seeds,
        }


def default_tier_policy_path() -> Path:
    return Scores.assets_dir() / "tier_policy.yaml"


def load_tier_policy_document(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"tier policy root must be a mapping: {path}")
    return document


def _parse_component_ids(raw: object, *, axis: str, step_id: str) -> tuple[int, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"step {step_id}: filters.{axis}.componentIds must be a list")
    ids: list[int] = []
    for value in raw:
        if not isinstance(value, int):
            raise ValueError(f"step {step_id}: filters.{axis}.componentIds entries must be ints")
        ids.append(value)
    return tuple(sorted(set(ids)))


def _parse_tech_levels_list(raw: object, *, axis: str, step_id: str) -> tuple[int, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"step {step_id}: filters.{axis}.techLevels must be a non-empty list when all is false"
        )
    levels: list[int] = []
    for value in raw:
        if not isinstance(value, int):
            raise ValueError(f"step {step_id}: filters.{axis}.techLevels entries must be integers")
        levels.append(value)
    return tuple(sorted(set(levels)))


def _parse_component_filter(raw: object, *, axis: str, step_id: str) -> ComponentFilter:
    if not isinstance(raw, dict):
        raise ValueError(f"step {step_id}: filters.{axis} must be a mapping")
    use_all = bool(raw.get("all", False))
    component_ids = _parse_component_ids(raw.get("componentIds"), axis=axis, step_id=step_id)
    if use_all:
        if "techLevels" in raw:
            raise ValueError(f"step {step_id}: filters.{axis} cannot set both all and techLevels")
        return ComponentFilter(all=True, component_ids=component_ids)
    tech_levels = _parse_tech_levels_list(raw.get("techLevels"), axis=axis, step_id=step_id)
    return ComponentFilter(all=False, tech_levels=tech_levels, component_ids=component_ids)


def _parse_catalog_filters(raw: object, *, step_id: str) -> InferenceCatalogFilters:
    if not isinstance(raw, dict):
        raise ValueError(f"step {step_id}: filters must be a mapping")
    parsed: dict[str, ComponentFilter] = {}
    for axis in FILTER_AXES:
        if axis not in raw:
            raise ValueError(f"step {step_id}: filters must include {axis}")
        parsed[axis] = _parse_component_filter(raw[axis], axis=axis, step_id=step_id)
    return InferenceCatalogFilters(
        hulls=parsed["hulls"],
        engines=parsed["engines"],
        beams=parsed["beams"],
        launchers=parsed["launchers"],
    )


def _parse_slot_mode(raw: object, *, field_name: str, step_id: str) -> SlotCountMode:
    if raw not in ("none", "partial"):
        raise ValueError(f"step {step_id}: {field_name} must be 'none' or 'partial'")
    return raw


def _parse_aggregate_allowlist(raw: object, *, step_id: str) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"step {step_id}: aggregateAllowlist must be a mapping")
    allowlist: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"step {step_id}: aggregateAllowlist keys must be strings")
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"step {step_id}: aggregateAllowlist values must be non-negative ints")
        allowlist[key] = value
    return allowlist


def _parse_policy_step(raw: dict[str, Any], *, index: int) -> InferenceTierPolicyStep:
    step_id = raw.get("id")
    if not isinstance(step_id, str) or not step_id:
        raise ValueError(f"step {index}: id must be a non-empty string")

    alpha = raw.get("alpha")
    if not isinstance(alpha, int) or alpha < 0:
        raise ValueError(f"step {step_id}: alpha must be a non-negative integer")

    max_seeds = raw.get("maxSeeds", DEFAULT_MAX_SEEDS)
    if not isinstance(max_seeds, int) or max_seeds < 0:
        raise ValueError(f"step {step_id}: maxSeeds must be a non-negative integer")

    return InferenceTierPolicyStep(
        id=step_id,
        filters=_parse_catalog_filters(raw.get("filters"), step_id=step_id),
        beam_slot_counts=_parse_slot_mode(
            raw.get("beamSlotCounts", "none"),
            field_name="beamSlotCounts",
            step_id=step_id,
        ),
        launcher_slot_counts=_parse_slot_mode(
            raw.get("launcherSlotCounts", "none"),
            field_name="launcherSlotCounts",
            step_id=step_id,
        ),
        aggregate_allowlist=_parse_aggregate_allowlist(
            raw.get("aggregateAllowlist"),
            step_id=step_id,
        ),
        alpha=alpha,
        max_seeds=max_seeds,
    )


def _component_filter_is_widening(
    prior: ComponentFilter,
    current: ComponentFilter,
    *,
    axis: str,
    prior_step_id: str,
    current_step_id: str,
) -> None:
    if prior.all and not current.all:
        raise ValueError(
            f"step {current_step_id}: filters.{axis} cannot narrow from all to techLevels "
            f"after step {prior_step_id} widened the axis"
        )
    if current.all:
        return
    if prior.all:
        return
    prior_set = set(prior.tech_levels)
    current_set = set(current.tech_levels)
    if not prior_set.issubset(current_set):
        raise ValueError(
            f"step {current_step_id}: filters.{axis}.techLevels must be a superset "
            f"of step {prior_step_id}"
        )


def _slot_mode_is_widening(
    prior: SlotCountMode,
    current: SlotCountMode,
    *,
    step_id: str,
    field_name: str,
) -> None:
    if prior == "partial" and current == "none":
        raise ValueError(f"step {step_id}: {field_name} cannot narrow from partial to none")


def validate_tier_policy_steps(steps: tuple[InferenceTierPolicyStep, ...]) -> None:
    if not steps:
        raise ValueError("tier policy must contain at least one step")
    if steps[-1].alpha != 0:
        raise ValueError("final policy step must have alpha: 0")

    for index in range(1, len(steps)):
        prior = steps[index - 1]
        current = steps[index]
        for axis in FILTER_AXES:
            _component_filter_is_widening(
                prior.filters.axis_filter(axis),
                current.filters.axis_filter(axis),
                axis=axis,
                prior_step_id=prior.id,
                current_step_id=current.id,
            )
        _slot_mode_is_widening(
            prior.beam_slot_counts,
            current.beam_slot_counts,
            step_id=current.id,
            field_name="beamSlotCounts",
        )
        _slot_mode_is_widening(
            prior.launcher_slot_counts,
            current.launcher_slot_counts,
            step_id=current.id,
            field_name="launcherSlotCounts",
        )

        prior_allowlist = prior.aggregate_allowlist
        current_allowlist = current.aggregate_allowlist
        for action_id, prior_cap in prior_allowlist.items():
            if action_id not in current_allowlist:
                raise ValueError(
                    f"step {current.id}: aggregateAllowlist must retain {action_id} "
                    f"from step {prior.id}"
                )
            if current_allowlist[action_id] < prior_cap:
                raise ValueError(
                    f"step {current.id}: aggregateAllowlist cap for {action_id} "
                    f"must be >= {prior_cap} from step {prior.id}"
                )
        for action_id, current_cap in current_allowlist.items():
            if action_id in prior_allowlist and current_cap < prior_allowlist[action_id]:
                raise ValueError(
                    f"step {current.id}: aggregateAllowlist cap for {action_id} "
                    f"must be >= {prior_allowlist[action_id]} from step {prior.id}"
                )


def parse_tier_policy_steps(document: dict[str, Any]) -> tuple[InferenceTierPolicyStep, ...]:
    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("tier policy must contain a non-empty steps list")
    steps = tuple(
        _parse_policy_step(raw_step, index=index) for index, raw_step in enumerate(raw_steps)
    )
    validate_tier_policy_steps(steps)
    return steps


def resolve_tier_policies(
    base_path: Path | None = None,
    overlay: TierPolicyOverlay | None = None,
) -> tuple[InferenceTierPolicyStep, ...]:
    """Load and validate the static tier policy ladder.

    When ``overlay`` is ``None``, returns YAML steps only. Overlay merge semantics are
    implemented in #78; non-``None`` overlays are accepted but not applied yet.
    """
    policy_path = default_tier_policy_path() if base_path is None else base_path
    steps = parse_tier_policy_steps(load_tier_policy_document(policy_path))
    if overlay is not None:
        return steps
    return steps


def compute_aggregate_admission_caps(
    steps: tuple[InferenceTierPolicyStep, ...],
    up_to_index: int,
) -> dict[str, int]:
    """First aggregateAllowlist appearance per key across policy steps 0..up_to_index."""
    caps: dict[str, int] = {}
    for step in steps[: up_to_index + 1]:
        for key, cap in step.aggregate_allowlist.items():
            if key not in caps:
                caps[key] = cap
    return caps


def resolved_aggregate_cap(action_id: str, allowlist: dict[str, int]) -> int | None:
    if action_id in allowlist:
        return allowlist[action_id]
    key = aggregate_allowlist_key(action_id)
    if key is not None:
        return allowlist.get(key)
    return None
