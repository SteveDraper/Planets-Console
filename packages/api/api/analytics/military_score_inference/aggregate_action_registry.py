"""Canonical aggregate-action metadata for military score inference."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from api.analytics.military_score_inference.models import (
    ProbabilityBinBounds,
)
from api.analytics.military_score_inference.scoring import (
    STARBASE_FIGHTER_SCORE_DELTA_2X,
    loaded_ship_fighter_score_delta_2x,
    loaded_ship_torpedo_score_delta_2x,
    planet_defense_post_score_delta_2x,
    starbase_defense_post_score_delta_2x,
    starbase_fighter_score_delta_2x,
)

SHIP_TORPS_LOADED_ACTION_PREFIX = "ship_torps_loaded_"

SHIP_TORPS_LOADED_ANY_PRIOR_KEY = "ship_torps_loaded_any"


def is_pooled_torp_load_prior_key(action_id: str) -> bool:
    return action_id == SHIP_TORPS_LOADED_ANY_PRIOR_KEY


def is_torp_load_action_id(action_id: str) -> bool:
    if not action_id.startswith(SHIP_TORPS_LOADED_ACTION_PREFIX):
        return False
    suffix = action_id.removeprefix(SHIP_TORPS_LOADED_ACTION_PREFIX)
    return suffix.isdecimal() and int(suffix) > 0


SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY = "ship_torps_per_type"
FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY = "fighter_transfers_per_direction"

MissingAggregatePolicy = Literal["required", "implicit_uniform"]


@dataclass(frozen=True)
class AggregateCatalogCaps:
    max_planet_defense_posts: int = 100
    max_starbase_defense_posts: int = 100
    max_starbase_fighters: int = 200
    max_ship_fighters: int = 500
    max_ship_torpedoes_per_type: int = 200
    max_fighter_transfers: int = 50


CatalogConfigCap = Callable[[AggregateCatalogCaps], int]


@dataclass(frozen=True)
class AggregatePriorFields:
    bin_bounds_key: str
    missing_aggregate_policy: MissingAggregatePolicy = "required"
    allowlist_key: str | None = None
    is_fighter_channel_member: bool = False


def aggregate_bin_bounds_for_spec(
    spec: AggregatePriorFields,
    *,
    tier_policy_path: Path | None = None,
) -> tuple[ProbabilityBinBounds, ...]:
    from api.analytics.military_score_inference.tier_policy import aggregate_bin_bounds_for_key

    return aggregate_bin_bounds_for_key(spec.bin_bounds_key, base_path=tier_policy_path)


def aggregate_bin_bounds_for_action(
    action_id: str,
    *,
    tier_policy_path: Path | None = None,
) -> tuple[ProbabilityBinBounds, ...]:
    spec = lookup_aggregate_action_spec(action_id)
    if spec is None:
        raise ValueError(f"unknown aggregate action id {action_id!r}")
    return aggregate_bin_bounds_for_spec(spec, tier_policy_path=tier_policy_path)


@dataclass(frozen=True)
class FixedAggregateSpec(AggregatePriorFields):
    catalog_label: str = ""
    score_delta_2x: Callable[[], int] | None = None
    catalog_config_cap: CatalogConfigCap | None = None


@dataclass(frozen=True)
class TemplateAggregateSpec(AggregatePriorFields):
    action_id_prefix: str = ""
    catalog_label_format: str = ""
    score_delta_2x_from_cost: Callable[[int], int] | None = None
    catalog_config_cap: CatalogConfigCap | None = None


AggregateActionSpec = FixedAggregateSpec | TemplateAggregateSpec


@dataclass(frozen=True)
class FixedAggregateRegistryEntry:
    action_id: str
    spec: FixedAggregateSpec


@dataclass(frozen=True)
class TemplateAggregateRegistryEntry:
    spec: TemplateAggregateSpec


AggregateRegistryEntry = FixedAggregateRegistryEntry | TemplateAggregateRegistryEntry


@dataclass(frozen=True)
class FixedAggregateSlot:
    action_id: str
    spec: FixedAggregateSpec
    catalog_label: str
    score_delta_2x: int


@dataclass(frozen=True)
class TemplateAggregateSlot:
    action_id: str
    spec: TemplateAggregateSpec
    entity_id: int


AggregateActionSlot = FixedAggregateSlot | TemplateAggregateSlot


def iter_aggregate_action_slots(
    *,
    eligible_torp_ids: frozenset[int],
) -> Iterator[AggregateActionSlot]:
    """Yield one catalog/prior slot per aggregate action from the canonical registry."""
    for entry in AGGREGATE_REGISTRY:
        if isinstance(entry, FixedAggregateRegistryEntry):
            spec = entry.spec
            if spec.score_delta_2x is None:
                raise ValueError(f"fixed aggregate slot missing score delta: {entry.action_id!r}")
            yield FixedAggregateSlot(
                action_id=entry.action_id,
                spec=spec,
                catalog_label=spec.catalog_label,
                score_delta_2x=spec.score_delta_2x(),
            )
            continue
        prefix = entry.spec.action_id_prefix
        if not prefix:
            raise ValueError("template aggregate registry entry missing action_id_prefix")
        for torp_id in sorted(eligible_torp_ids):
            yield TemplateAggregateSlot(
                action_id=f"{prefix}{torp_id}",
                spec=entry.spec,
                entity_id=torp_id,
            )


# Catalog build order: config-cap histogram actions, torpedo template, fighter transfers.
AGGREGATE_REGISTRY: tuple[AggregateRegistryEntry, ...] = (
    FixedAggregateRegistryEntry(
        action_id="planet_defense_posts_added_total",
        spec=FixedAggregateSpec(
            bin_bounds_key="planet_defense_posts_added_total",
            catalog_label="Planet defense posts added",
            score_delta_2x=planet_defense_post_score_delta_2x,
            catalog_config_cap=lambda config: config.max_planet_defense_posts,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="starbase_defense_posts_added_total",
        spec=FixedAggregateSpec(
            bin_bounds_key="starbase_defense_posts_added_total",
            catalog_label="Starbase defense posts added",
            score_delta_2x=starbase_defense_post_score_delta_2x,
            catalog_config_cap=lambda config: config.max_starbase_defense_posts,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="starbase_fighters_added_total",
        spec=FixedAggregateSpec(
            bin_bounds_key="starbase_fighters_added_total",
            is_fighter_channel_member=True,
            catalog_label="Starbase fighters added",
            score_delta_2x=starbase_fighter_score_delta_2x,
            catalog_config_cap=lambda config: config.max_starbase_fighters,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="ship_fighters_added_total",
        spec=FixedAggregateSpec(
            bin_bounds_key="ship_fighters_added_total",
            is_fighter_channel_member=True,
            catalog_label="Ship fighters added",
            score_delta_2x=loaded_ship_fighter_score_delta_2x,
            catalog_config_cap=lambda config: config.max_ship_fighters,
        ),
    ),
    TemplateAggregateRegistryEntry(
        spec=TemplateAggregateSpec(
            bin_bounds_key=SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY,
            missing_aggregate_policy="implicit_uniform",
            allowlist_key=SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY,
            action_id_prefix=SHIP_TORPS_LOADED_ACTION_PREFIX,
            catalog_config_cap=lambda config: config.max_ship_torpedoes_per_type,
            catalog_label_format="Ship torpedoes loaded ({name})",
            score_delta_2x_from_cost=loaded_ship_torpedo_score_delta_2x,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="fighters_starbase_to_ship",
        spec=FixedAggregateSpec(
            bin_bounds_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
            allowlist_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
            is_fighter_channel_member=True,
            catalog_label="Fighters transferred starbase to ship",
            score_delta_2x=lambda: STARBASE_FIGHTER_SCORE_DELTA_2X,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="fighters_ship_to_starbase",
        spec=FixedAggregateSpec(
            bin_bounds_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
            allowlist_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
            is_fighter_channel_member=True,
            catalog_label="Fighters transferred ship to starbase",
            score_delta_2x=lambda: -STARBASE_FIGHTER_SCORE_DELTA_2X,
        ),
    ),
)


def _build_aggregate_action_spec_caches() -> tuple[
    dict[str, FixedAggregateSpec],
    str | None,
    TemplateAggregateSpec | None,
]:
    fixed_specs: dict[str, FixedAggregateSpec] = {}
    template_prefix: str | None = None
    template_spec: TemplateAggregateSpec | None = None
    for entry in AGGREGATE_REGISTRY:
        if isinstance(entry, FixedAggregateRegistryEntry):
            fixed_specs[entry.action_id] = entry.spec
            continue
        prefix = entry.spec.action_id_prefix
        if not prefix:
            raise ValueError("template aggregate registry entry missing action_id_prefix")
        if template_prefix is not None:
            raise ValueError("multiple template aggregate registry entries are not supported")
        template_prefix = prefix
        template_spec = entry.spec
    return fixed_specs, template_prefix, template_spec


AGGREGATE_ACTION_SPECS, _AGGREGATE_TEMPLATE_PREFIX, _AGGREGATE_TEMPLATE_SPEC = (
    _build_aggregate_action_spec_caches()
)


def _is_valid_template_action_id(action_id: str, prefix: str) -> bool:
    suffix = action_id.removeprefix(prefix)
    return suffix.isdecimal() and int(suffix) > 0


def lookup_aggregate_action_spec(action_id: str) -> AggregateActionSpec | None:
    spec = AGGREGATE_ACTION_SPECS.get(action_id)
    if spec is not None:
        return spec
    if (
        _AGGREGATE_TEMPLATE_PREFIX is not None
        and _AGGREGATE_TEMPLATE_SPEC is not None
        and action_id.startswith(_AGGREGATE_TEMPLATE_PREFIX)
        and _is_valid_template_action_id(action_id, _AGGREGATE_TEMPLATE_PREFIX)
    ):
        return _AGGREGATE_TEMPLATE_SPEC
    return None


def resolved_aggregate_cap(action_id: str, allowlist: dict[str, int]) -> int | None:
    """Return the allowlist cap for one aggregate action id."""
    if action_id in allowlist:
        return allowlist[action_id]
    spec = lookup_aggregate_action_spec(action_id)
    if spec is not None and spec.allowlist_key is not None:
        return allowlist.get(spec.allowlist_key)
    return None
