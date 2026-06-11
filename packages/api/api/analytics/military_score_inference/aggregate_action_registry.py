"""Canonical aggregate-action metadata for military score inference."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.models import ProbabilityBinBounds
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
CatalogBuildPhase = Literal["pre_torpedo", "torpedo", "post_torpedo"]

CATALOG_BUILD_PHASE_ORDER: tuple[CatalogBuildPhase, ...] = (
    "pre_torpedo",
    "torpedo",
    "post_torpedo",
)


@dataclass(frozen=True)
class AggregateActionSpec:
    prior_shape: PriorShape
    bin_bounds: tuple[ProbabilityBinBounds, ...] | None
    allowlist_key: str | None = None
    is_fighter_channel_member: bool = False
    is_fine_grained_slack: bool = False
    catalog_label: str = ""
    score_delta_2x: Callable[[], int] | None = None
    config_cap_field: str | None = None
    catalog_build_phase: CatalogBuildPhase | None = None


@dataclass(frozen=True)
class AggregateActionTemplateSpec:
    action_id_prefix: str
    prior_shape: PriorShape
    bin_bounds: tuple[ProbabilityBinBounds, ...] | None
    catalog_build_phase: CatalogBuildPhase
    config_cap_field: str
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


AGGREGATE_ACTION_SPECS: dict[str, AggregateActionSpec] = {
    "planet_defense_posts_added_total": AggregateActionSpec(
        prior_shape="histogram",
        bin_bounds=PLANET_DEFENSE_POST_BIN_BOUNDS,
        is_fine_grained_slack=True,
        catalog_label="Planet defense posts added",
        score_delta_2x=planet_defense_post_score_delta_2x,
        config_cap_field="max_planet_defense_posts",
        catalog_build_phase="pre_torpedo",
    ),
    "starbase_defense_posts_added_total": AggregateActionSpec(
        prior_shape="histogram",
        bin_bounds=STARBASE_DEFENSE_POST_BIN_BOUNDS,
        is_fine_grained_slack=True,
        catalog_label="Starbase defense posts added",
        score_delta_2x=starbase_defense_post_score_delta_2x,
        config_cap_field="max_starbase_defense_posts",
        catalog_build_phase="pre_torpedo",
    ),
    "starbase_fighters_added_total": AggregateActionSpec(
        prior_shape="histogram",
        bin_bounds=STARBASE_FIGHTER_BIN_BOUNDS,
        is_fighter_channel_member=True,
        is_fine_grained_slack=True,
        catalog_label="Starbase fighters added",
        score_delta_2x=starbase_fighter_score_delta_2x,
        config_cap_field="max_starbase_fighters",
        catalog_build_phase="pre_torpedo",
    ),
    "ship_fighters_added_total": AggregateActionSpec(
        prior_shape="histogram",
        bin_bounds=SHIP_FIGHTER_BIN_BOUNDS,
        is_fighter_channel_member=True,
        is_fine_grained_slack=True,
        catalog_label="Ship fighters added",
        score_delta_2x=loaded_ship_fighter_score_delta_2x,
        config_cap_field="max_ship_fighters",
        catalog_build_phase="pre_torpedo",
    ),
    "fighters_starbase_to_ship": AggregateActionSpec(
        prior_shape="counts",
        bin_bounds=None,
        allowlist_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
        is_fighter_channel_member=True,
        is_fine_grained_slack=True,
        catalog_label="Fighters transferred starbase to ship",
        score_delta_2x=lambda: STARBASE_FIGHTER_SCORE_DELTA_2X,
        catalog_build_phase="post_torpedo",
    ),
    "fighters_ship_to_starbase": AggregateActionSpec(
        prior_shape="counts",
        bin_bounds=None,
        allowlist_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
        is_fighter_channel_member=True,
        is_fine_grained_slack=True,
        catalog_label="Fighters transferred ship to starbase",
        score_delta_2x=lambda: -STARBASE_FIGHTER_SCORE_DELTA_2X,
        catalog_build_phase="post_torpedo",
    ),
}

AGGREGATE_ACTION_TEMPLATES: tuple[AggregateActionTemplateSpec, ...] = (
    AggregateActionTemplateSpec(
        action_id_prefix=SHIP_TORPS_LOADED_ACTION_PREFIX,
        prior_shape="histogram",
        bin_bounds=SHIP_TORPEDO_BIN_BOUNDS,
        allowlist_key=SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY,
        is_fine_grained_slack=True,
        catalog_build_phase="torpedo",
        config_cap_field="max_ship_torpedoes_per_type",
        catalog_label_format="Ship torpedoes loaded ({name})",
        score_delta_2x_from_cost=loaded_ship_torpedo_score_delta_2x,
    ),
)


def lookup_aggregate_action_template(action_id: str) -> AggregateActionTemplateSpec | None:
    for template in AGGREGATE_ACTION_TEMPLATES:
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


def base_bin_bounds_for_action(action_id: str) -> tuple[ProbabilityBinBounds, ...] | None:
    spec = lookup_aggregate_action_spec(action_id)
    if spec is None:
        return None
    return spec.bin_bounds


def magnitude_bin_index(magnitude: int, bin_bounds: tuple[ProbabilityBinBounds, ...]) -> int:
    """Return the index of the magnitude bin for a positive magnitude count."""
    for index, bound in enumerate(bin_bounds):
        lower_bound = 1 if bound.lower_count == 0 else bound.lower_count
        if lower_bound <= magnitude <= bound.upper_count:
            return index
    return len(bin_bounds) - 1
