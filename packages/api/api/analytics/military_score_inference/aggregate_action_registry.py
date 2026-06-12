"""Canonical aggregate-action metadata for military score inference."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, Protocol

from api.analytics.military_score_inference.models import (
    MagnitudeCountBounds,
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

SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY = "ship_torps_per_type"
FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY = "fighter_transfers_per_direction"

DEFENSE_POST_BIN_BOUNDS = (
    ProbabilityBinBounds("modest build-up", 0, 10),
    ProbabilityBinBounds("heavy build-up", 11, 50),
    ProbabilityBinBounds("extreme build-up", 51, 100),
)
PLANET_DEFENSE_POST_BIN_BOUNDS = DEFENSE_POST_BIN_BOUNDS
STARBASE_DEFENSE_POST_BIN_BOUNDS = DEFENSE_POST_BIN_BOUNDS
STARBASE_FIGHTER_BIN_BOUNDS = (
    ProbabilityBinBounds("modest build-up", 0, 20),
    ProbabilityBinBounds("heavy build-up", 21, 100),
    ProbabilityBinBounds("extreme build-up", 101, 200),
)
SHIP_FIGHTER_BIN_BOUNDS = (
    ProbabilityBinBounds("modest load", 0, 20),
    ProbabilityBinBounds("heavy load", 21, 100),
    ProbabilityBinBounds("extreme load", 101, 500),
)
SHIP_TORPEDO_BIN_BOUNDS = (
    ProbabilityBinBounds("modest load", 0, 40),
    ProbabilityBinBounds("heavy load", 41, 100),
    ProbabilityBinBounds("extreme load", 101, 200),
)

PriorShape = Literal["histogram", "counts"]
MissingAggregatePolicy = Literal["required", "implicit_uniform"]


class CatalogConfig(Protocol):
    max_planet_defense_posts: int
    max_starbase_defense_posts: int
    max_starbase_fighters: int
    max_ship_fighters: int
    max_ship_torpedoes_per_type: int
    max_fighter_transfers: int


CatalogConfigCap = Callable[[CatalogConfig], int]


@dataclass(frozen=True)
class AggregatePriorFields:
    prior_shape: PriorShape
    bin_bounds: tuple[ProbabilityBinBounds, ...] | None
    missing_aggregate_policy: MissingAggregatePolicy = "required"
    allowlist_key: str | None = None
    is_fighter_channel_member: bool = False
    is_fine_grained_slack: bool = False


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
            prior_shape="histogram",
            bin_bounds=PLANET_DEFENSE_POST_BIN_BOUNDS,
            is_fine_grained_slack=True,
            catalog_label="Planet defense posts added",
            score_delta_2x=planet_defense_post_score_delta_2x,
            catalog_config_cap=lambda config: config.max_planet_defense_posts,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="starbase_defense_posts_added_total",
        spec=FixedAggregateSpec(
            prior_shape="histogram",
            bin_bounds=STARBASE_DEFENSE_POST_BIN_BOUNDS,
            is_fine_grained_slack=True,
            catalog_label="Starbase defense posts added",
            score_delta_2x=starbase_defense_post_score_delta_2x,
            catalog_config_cap=lambda config: config.max_starbase_defense_posts,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="starbase_fighters_added_total",
        spec=FixedAggregateSpec(
            prior_shape="histogram",
            bin_bounds=STARBASE_FIGHTER_BIN_BOUNDS,
            is_fighter_channel_member=True,
            is_fine_grained_slack=True,
            catalog_label="Starbase fighters added",
            score_delta_2x=starbase_fighter_score_delta_2x,
            catalog_config_cap=lambda config: config.max_starbase_fighters,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="ship_fighters_added_total",
        spec=FixedAggregateSpec(
            prior_shape="histogram",
            bin_bounds=SHIP_FIGHTER_BIN_BOUNDS,
            is_fighter_channel_member=True,
            is_fine_grained_slack=True,
            catalog_label="Ship fighters added",
            score_delta_2x=loaded_ship_fighter_score_delta_2x,
            catalog_config_cap=lambda config: config.max_ship_fighters,
        ),
    ),
    TemplateAggregateRegistryEntry(
        spec=TemplateAggregateSpec(
            prior_shape="histogram",
            bin_bounds=SHIP_TORPEDO_BIN_BOUNDS,
            missing_aggregate_policy="implicit_uniform",
            allowlist_key=SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY,
            is_fine_grained_slack=True,
            action_id_prefix=SHIP_TORPS_LOADED_ACTION_PREFIX,
            catalog_config_cap=lambda config: config.max_ship_torpedoes_per_type,
            catalog_label_format="Ship torpedoes loaded ({name})",
            score_delta_2x_from_cost=loaded_ship_torpedo_score_delta_2x,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="fighters_starbase_to_ship",
        spec=FixedAggregateSpec(
            prior_shape="counts",
            bin_bounds=None,
            allowlist_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
            is_fighter_channel_member=True,
            is_fine_grained_slack=True,
            catalog_label="Fighters transferred starbase to ship",
            score_delta_2x=lambda: STARBASE_FIGHTER_SCORE_DELTA_2X,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="fighters_ship_to_starbase",
        spec=FixedAggregateSpec(
            prior_shape="counts",
            bin_bounds=None,
            allowlist_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
            is_fighter_channel_member=True,
            is_fine_grained_slack=True,
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


def lookup_aggregate_action_spec(action_id: str) -> AggregateActionSpec | None:
    spec = AGGREGATE_ACTION_SPECS.get(action_id)
    if spec is not None:
        return spec
    if (
        _AGGREGATE_TEMPLATE_PREFIX is not None
        and _AGGREGATE_TEMPLATE_SPEC is not None
        and action_id.startswith(_AGGREGATE_TEMPLATE_PREFIX)
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


def magnitude_bin_index(magnitude: int, bin_bounds: tuple[MagnitudeCountBounds, ...]) -> int:
    """Return the index of the magnitude bin for a positive magnitude count."""
    for index, bound in enumerate(bin_bounds):
        lower_bound = 1 if bound.lower_count == 0 else bound.lower_count
        if lower_bound <= magnitude <= bound.upper_count:
            return index
    return len(bin_bounds) - 1
