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
