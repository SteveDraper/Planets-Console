"""Canonical aggregate-action metadata for military score inference."""

from __future__ import annotations

SHIP_TORPS_LOADED_ACTION_PREFIX = "ship_torps_loaded_"

SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY = "ship_torps_per_type"
FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY = "fighter_transfers_per_direction"

HISTOGRAM_EXACT_ACTION_IDS = frozenset(
    {
        "planet_defense_posts_added_total",
        "starbase_defense_posts_added_total",
        "starbase_fighters_added_total",
        "ship_fighters_added_total",
    }
)

COUNTS_AGGREGATE_ACTION_IDS = frozenset(
    {
        "fighters_starbase_to_ship",
        "fighters_ship_to_starbase",
    }
)

FIGHTER_CHANNEL_MEMBER_IDS = frozenset(
    {
        "starbase_fighters_added_total",
        "ship_fighters_added_total",
        "fighters_starbase_to_ship",
        "fighters_ship_to_starbase",
    }
)

FINE_GRAINED_SLACK_EXACT_ACTION_IDS = frozenset(
    {
        "planet_defense_posts_added_total",
        "starbase_defense_posts_added_total",
        "starbase_fighters_added_total",
        "ship_fighters_added_total",
        "fighters_starbase_to_ship",
        "fighters_ship_to_starbase",
    }
)


def is_ship_torps_loaded_action(action_id: str) -> bool:
    return action_id.startswith(SHIP_TORPS_LOADED_ACTION_PREFIX)


def is_histogram_aggregate_action(action_id: str) -> bool:
    if action_id in HISTOGRAM_EXACT_ACTION_IDS:
        return True
    return is_ship_torps_loaded_action(action_id)


def is_counts_aggregate_action(action_id: str) -> bool:
    return action_id in COUNTS_AGGREGATE_ACTION_IDS


def is_fine_grained_slack_action(action_id: str) -> bool:
    if action_id in FINE_GRAINED_SLACK_EXACT_ACTION_IDS:
        return True
    return is_ship_torps_loaded_action(action_id)


def is_fighter_channel_member(action_id: str) -> bool:
    return action_id in FIGHTER_CHANNEL_MEMBER_IDS


def aggregate_allowlist_key(action_id: str) -> str | None:
    if is_ship_torps_loaded_action(action_id):
        return SHIP_TORPS_PER_TYPE_ALLOWLIST_KEY
    if action_id in COUNTS_AGGREGATE_ACTION_IDS:
        return FIGHTER_TRANSFERS_PER_DIRECTION_ALLOWLIST_KEY
    return None
