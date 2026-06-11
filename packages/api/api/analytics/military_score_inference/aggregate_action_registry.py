"""Canonical aggregate-action metadata for military score inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.models import ProbabilityBucket

SHIP_TORPS_LOADED_ACTION_PREFIX = "ship_torps_loaded_"

SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY = "ship_torps_per_type"
FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY = "fighter_transfers_per_direction"

PLANET_DEFENSE_POST_BUCKETS = (
    ProbabilityBucket("modest build-up", 0, 10, 100),
    ProbabilityBucket("heavy build-up", 11, 50, 20),
    ProbabilityBucket("extreme build-up", 51, 100, 5),
)
STARBASE_DEFENSE_POST_BUCKETS = (
    ProbabilityBucket("modest build-up", 0, 10, 100),
    ProbabilityBucket("heavy build-up", 11, 50, 20),
    ProbabilityBucket("extreme build-up", 51, 100, 5),
)
STARBASE_FIGHTER_BUCKETS = (
    ProbabilityBucket("modest build-up", 0, 20, 80),
    ProbabilityBucket("heavy build-up", 21, 100, 15),
    ProbabilityBucket("extreme build-up", 101, 200, 3),
)
SHIP_FIGHTER_BUCKETS = (
    ProbabilityBucket("modest load", 0, 20, 70),
    ProbabilityBucket("heavy load", 21, 100, 20),
    ProbabilityBucket("extreme load", 101, 500, 5),
)
SHIP_TORPEDO_BUCKETS = (
    ProbabilityBucket("modest load", 0, 40, 70),
    ProbabilityBucket("heavy load", 41, 100, 70),
    ProbabilityBucket("extreme load", 101, 200, 5),
)

PriorShape = Literal["histogram", "counts"]


@dataclass(frozen=True)
class AggregateActionSpec:
    prior_shape: PriorShape
    buckets: tuple[ProbabilityBucket, ...] | None
    allowlist_key: str | None = None
    is_fighter_channel_member: bool = False
    is_fine_grained_slack: bool = False


AGGREGATE_ACTION_SPECS: dict[str, AggregateActionSpec] = {
    "planet_defense_posts_added_total": AggregateActionSpec(
        prior_shape="histogram",
        buckets=PLANET_DEFENSE_POST_BUCKETS,
        is_fine_grained_slack=True,
    ),
    "starbase_defense_posts_added_total": AggregateActionSpec(
        prior_shape="histogram",
        buckets=STARBASE_DEFENSE_POST_BUCKETS,
        is_fine_grained_slack=True,
    ),
    "starbase_fighters_added_total": AggregateActionSpec(
        prior_shape="histogram",
        buckets=STARBASE_FIGHTER_BUCKETS,
        is_fighter_channel_member=True,
        is_fine_grained_slack=True,
    ),
    "ship_fighters_added_total": AggregateActionSpec(
        prior_shape="histogram",
        buckets=SHIP_FIGHTER_BUCKETS,
        is_fighter_channel_member=True,
        is_fine_grained_slack=True,
    ),
    "fighters_starbase_to_ship": AggregateActionSpec(
        prior_shape="counts",
        buckets=None,
        allowlist_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
        is_fighter_channel_member=True,
        is_fine_grained_slack=True,
    ),
    "fighters_ship_to_starbase": AggregateActionSpec(
        prior_shape="counts",
        buckets=None,
        allowlist_key=FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY,
        is_fighter_channel_member=True,
        is_fine_grained_slack=True,
    ),
}

SHIP_TORPS_LOADED_SPEC = AggregateActionSpec(
    prior_shape="histogram",
    buckets=SHIP_TORPEDO_BUCKETS,
    allowlist_key=SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY,
    is_fine_grained_slack=True,
)


def lookup_aggregate_action_spec(action_id: str) -> AggregateActionSpec | None:
    spec = AGGREGATE_ACTION_SPECS.get(action_id)
    if spec is not None:
        return spec
    if action_id.startswith(SHIP_TORPS_LOADED_ACTION_PREFIX):
        return SHIP_TORPS_LOADED_SPEC
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


def base_buckets_for_action(action_id: str) -> tuple[ProbabilityBucket, ...] | None:
    spec = lookup_aggregate_action_spec(action_id)
    if spec is None:
        return None
    return spec.buckets


def magnitude_bin_index(magnitude: int, buckets: tuple[ProbabilityBucket, ...]) -> int:
    """Return the index of the magnitude bin for a positive magnitude count."""
    for index, bucket in enumerate(buckets):
        lower_bound = 1 if bucket.lower_count == 0 else bucket.lower_count
        if lower_bound <= magnitude <= bucket.upper_count:
            return index
    return len(buckets) - 1
