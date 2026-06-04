"""Race-specific Planets.nu rules and numeric traits.

Planets.nu ``raceid`` values and mechanics that differ by race belong here, not in
analytics or accelerated-start helpers. Game-wide homeworld defaults stay elsewhere.
"""

from api.models.game import GameSettings

EVIL_EMPIRE_RACE_ID = 8

EVIL_EMPIRE_FREE_STARBASE_FIGHTERS_BASE = 5


def is_evil_empire(race_id: int) -> bool:
    return race_id == EVIL_EMPIRE_RACE_ID


def evil_empire_free_starbase_fighters_per_host_turn(settings: GameSettings) -> int:
    """Free fighters an Evil Empire starbase may build each host turn when stocked."""
    return EVIL_EMPIRE_FREE_STARBASE_FIGHTERS_BASE + settings.freestarbasefighters5adjustment
