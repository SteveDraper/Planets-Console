"""Default magnitude-bin definitions for aggregate inference actions."""

from api.analytics.military_score_inference.models import ProbabilityBucket

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

_SHIP_TORPS_LOADED_ACTION_PREFIX = "ship_torps_loaded_"

_BUCKETS_BY_EXACT_ACTION_ID: dict[str, tuple[ProbabilityBucket, ...]] = {
    "planet_defense_posts_added_total": PLANET_DEFENSE_POST_BUCKETS,
    "starbase_defense_posts_added_total": STARBASE_DEFENSE_POST_BUCKETS,
    "starbase_fighters_added_total": STARBASE_FIGHTER_BUCKETS,
    "ship_fighters_added_total": SHIP_FIGHTER_BUCKETS,
}

BUCKETED_ACTION_IDS = frozenset(_BUCKETS_BY_EXACT_ACTION_ID)


def base_buckets_for_action(action_id: str) -> tuple[ProbabilityBucket, ...] | None:
    base_buckets = _BUCKETS_BY_EXACT_ACTION_ID.get(action_id)
    if base_buckets is not None:
        return base_buckets
    if action_id.startswith(_SHIP_TORPS_LOADED_ACTION_PREFIX):
        return SHIP_TORPEDO_BUCKETS
    return None
