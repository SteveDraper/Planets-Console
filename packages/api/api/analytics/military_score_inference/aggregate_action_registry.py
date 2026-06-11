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


class PriorCatalogProbabilityWeightSource(Protocol):
    def aggregate_probability_weight(self, action_id: str) -> int | None: ...


class CatalogConfig(Protocol):
    max_planet_defense_posts: int
    max_starbase_defense_posts: int
    max_starbase_fighters: int
    max_ship_fighters: int
    max_ship_torpedoes_per_type: int
    max_fighter_transfers: int


CatalogConfigCap = Callable[[CatalogConfig], int]


@dataclass(frozen=True)
class AggregateActionSpec:
    prior_shape: PriorShape
    bin_bounds: tuple[ProbabilityBinBounds, ...] | None
    allowlist_key: str | None = None
    is_fighter_channel_member: bool = False
    is_fine_grained_slack: bool = False
    catalog_label: str = ""
    score_delta_2x: Callable[[], int] | None = None
    catalog_config_cap: CatalogConfigCap | None = None

    def catalog_probability_weight(
        self,
        action_id: str,
        prior_catalog: PriorCatalogProbabilityWeightSource,
    ) -> int:
        if self.prior_shape == "histogram":
            return 0
        if self.prior_shape == "counts":
            prior_weight = prior_catalog.aggregate_probability_weight(action_id)
            if prior_weight is None:
                raise ValueError(
                    f"incomplete prior: missing counts aggregate weight for action {action_id!r}"
                )
            return prior_weight
        raise ValueError(f"unknown prior_shape {self.prior_shape!r} for action {action_id!r}")


@dataclass(frozen=True)
class AggregateActionTemplateSpec:
    action_id_prefix: str
    prior_shape: PriorShape
    bin_bounds: tuple[ProbabilityBinBounds, ...] | None
    catalog_config_cap: CatalogConfigCap
    catalog_label_format: str
    score_delta_2x_from_cost: Callable[[int], int]
    allowlist_key: str | None = None
    is_fine_grained_slack: bool = False

    def aggregate_spec(self) -> AggregateActionSpec:
        return AggregateActionSpec(
            prior_shape=self.prior_shape,
            bin_bounds=self.bin_bounds,
            allowlist_key=self.allowlist_key,
            is_fine_grained_slack=self.is_fine_grained_slack,
        )

    def action_id_for_entity_id(self, entity_id: int) -> str:
        return f"{self.action_id_prefix}{entity_id}"


@dataclass(frozen=True)
class FixedAggregateRegistryEntry:
    action_id: str
    spec: AggregateActionSpec


@dataclass(frozen=True)
class TemplateAggregateRegistryEntry:
    template: AggregateActionTemplateSpec


AggregateRegistryEntry = FixedAggregateRegistryEntry | TemplateAggregateRegistryEntry

AssetRequirement = Literal["required", "optional_uniform_histogram"]


@dataclass(frozen=True)
class AggregateActionSlot:
    action_id: str
    spec: AggregateActionSpec
    asset_requirement: AssetRequirement
    template: AggregateActionTemplateSpec | None = None
    entity_id: int | None = None


def iter_aggregate_action_slots(
    *,
    eligible_torp_ids: frozenset[int],
) -> Iterator[AggregateActionSlot]:
    """Yield one catalog/prior slot per aggregate action from the canonical registry."""
    for entry in AGGREGATE_REGISTRY:
        if isinstance(entry, FixedAggregateRegistryEntry):
            yield AggregateActionSlot(
                action_id=entry.action_id,
                spec=entry.spec,
                asset_requirement="required",
            )
            continue
        template = entry.template
        for torp_id in sorted(eligible_torp_ids):
            yield AggregateActionSlot(
                action_id=template.action_id_for_entity_id(torp_id),
                spec=template.aggregate_spec(),
                asset_requirement="optional_uniform_histogram",
                template=template,
                entity_id=torp_id,
            )


# Catalog build order: config-cap histogram actions, torpedo template, fighter transfers.
AGGREGATE_REGISTRY: tuple[AggregateRegistryEntry, ...] = (
    FixedAggregateRegistryEntry(
        action_id="planet_defense_posts_added_total",
        spec=AggregateActionSpec(
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
        spec=AggregateActionSpec(
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
        spec=AggregateActionSpec(
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
        spec=AggregateActionSpec(
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
        template=AggregateActionTemplateSpec(
            action_id_prefix=SHIP_TORPS_LOADED_ACTION_PREFIX,
            prior_shape="histogram",
            bin_bounds=SHIP_TORPEDO_BIN_BOUNDS,
            allowlist_key=SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY,
            is_fine_grained_slack=True,
            catalog_config_cap=lambda config: config.max_ship_torpedoes_per_type,
            catalog_label_format="Ship torpedoes loaded ({name})",
            score_delta_2x_from_cost=loaded_ship_torpedo_score_delta_2x,
        ),
    ),
    FixedAggregateRegistryEntry(
        action_id="fighters_starbase_to_ship",
        spec=AggregateActionSpec(
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
        spec=AggregateActionSpec(
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

AGGREGATE_ACTION_SPECS: dict[str, AggregateActionSpec] = {
    entry.action_id: entry.spec
    for entry in AGGREGATE_REGISTRY
    if isinstance(entry, FixedAggregateRegistryEntry)
}


def lookup_aggregate_action_template(action_id: str) -> AggregateActionTemplateSpec | None:
    for entry in AGGREGATE_REGISTRY:
        if isinstance(entry, TemplateAggregateRegistryEntry):
            template = entry.template
            if action_id.startswith(template.action_id_prefix):
                return template
    return None


def lookup_aggregate_action_spec(action_id: str) -> AggregateActionSpec | None:
    spec = AGGREGATE_ACTION_SPECS.get(action_id)
    if spec is not None:
        return spec
    template = lookup_aggregate_action_template(action_id)
    if template is not None:
        return template.aggregate_spec()
    return None


def is_ship_torps_loaded_action(action_id: str) -> bool:
    return action_id.startswith(SHIP_TORPS_LOADED_ACTION_PREFIX)


def is_histogram_aggregate_action(action_id: str) -> bool:
    spec = lookup_aggregate_action_spec(action_id)
    return spec is not None and spec.prior_shape == "histogram"


def is_counts_aggregate_action(action_id: str) -> bool:
    spec = lookup_aggregate_action_spec(action_id)
    return spec is not None and spec.prior_shape == "counts"


def is_fine_grained_slack_action(action_id: str) -> bool:
    spec = lookup_aggregate_action_spec(action_id)
    return spec is not None and spec.is_fine_grained_slack


def is_fighter_channel_member(action_id: str) -> bool:
    spec = lookup_aggregate_action_spec(action_id)
    return spec is not None and spec.is_fighter_channel_member


def aggregate_allowlist_key(action_id: str) -> str | None:
    spec = lookup_aggregate_action_spec(action_id)
    if spec is None:
        return None
    return spec.allowlist_key


def resolved_aggregate_cap(action_id: str, allowlist: dict[str, int]) -> int | None:
    """Return the allowlist cap for one aggregate action id."""
    if action_id in allowlist:
        return allowlist[action_id]
    key = aggregate_allowlist_key(action_id)
    if key is not None:
        return allowlist.get(key)
    return None


def base_bin_bounds_for_action(action_id: str) -> tuple[ProbabilityBinBounds, ...] | None:
    spec = lookup_aggregate_action_spec(action_id)
    if spec is None:
        return None
    return spec.bin_bounds


def magnitude_bin_index(magnitude: int, bin_bounds: tuple[MagnitudeCountBounds, ...]) -> int:
    """Return the index of the magnitude bin for a positive magnitude count."""
    for index, bound in enumerate(bin_bounds):
        lower_bound = 1 if bound.lower_count == 0 else bound.lower_count
        if lower_bound <= magnitude <= bound.upper_count:
            return index
    return len(bin_bounds) - 1
