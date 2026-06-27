"""Public scores boundary for scoreboard placeholder metadata.

Fleet and other analytics consumers should import placeholder-target helpers
from this module rather than from ``scoreboard_placeholder_targets`` directly.
"""

from api.analytics.scores.scoreboard_placeholder_targets import (
    ScoreboardPlaceholderTarget,
    homeworld_starting_freighter_hull_id,
    homeworld_starting_inventory_counts,
    is_first_reliable_accelerated_shell_turn,
    scoreboard_placeholder_targets,
    should_seed_homeworld_starting_inventory,
)

__all__ = (
    "ScoreboardPlaceholderTarget",
    "homeworld_starting_freighter_hull_id",
    "homeworld_starting_inventory_counts",
    "is_first_reliable_accelerated_shell_turn",
    "scoreboard_placeholder_targets",
    "should_seed_homeworld_starting_inventory",
)
