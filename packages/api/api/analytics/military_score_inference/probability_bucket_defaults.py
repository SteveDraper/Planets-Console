"""Default magnitude-bin definitions for aggregate inference actions."""

from api.analytics.military_score_inference.aggregate_action_registry import (
    BUCKETED_ACTION_IDS,
    PLANET_DEFENSE_POST_BUCKETS,
    SHIP_FIGHTER_BUCKETS,
    SHIP_TORPEDO_BUCKETS,
    STARBASE_DEFENSE_POST_BUCKETS,
    STARBASE_FIGHTER_BUCKETS,
    base_buckets_for_action,
    magnitude_bin_index,
)

__all__ = [
    "BUCKETED_ACTION_IDS",
    "PLANET_DEFENSE_POST_BUCKETS",
    "SHIP_FIGHTER_BUCKETS",
    "SHIP_TORPEDO_BUCKETS",
    "STARBASE_DEFENSE_POST_BUCKETS",
    "STARBASE_FIGHTER_BUCKETS",
    "base_buckets_for_action",
    "magnitude_bin_index",
]
