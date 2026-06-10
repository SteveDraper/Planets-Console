"""Scaled military-score contribution helpers for build inference."""

LOADED_SHIP_FIGHTER_SCORE_DELTA_2X = 250
LOADED_TORPEDO_AMMO_MINERALS = 3
STARBASE_FIGHTER_SCORE_DELTA_2X = 125
STARBASE_DEFENSE_POST_SCORE_DELTA_2X = 15
PLANET_DEFENSE_POST_SCORE_DELTA_2X = 11


def construction_value(megacredits: int, minerals: int) -> int:
    """AutoScore-style construction value: megacredits plus five times minerals."""
    return megacredits + 5 * minerals


def ship_construction_score_delta_2x(
    construction_megacredits: int,
    construction_minerals: int,
) -> int:
    """Scaled military-score delta for one ship hull plus fitted components."""
    return 2 * construction_value(construction_megacredits, construction_minerals)


def loaded_ship_fighter_score_delta_2x(count: int = 1) -> int:
    """Scaled score delta for fighters loaded onto ships (full military value)."""
    return LOADED_SHIP_FIGHTER_SCORE_DELTA_2X * count


def loaded_ship_torpedo_score_delta_2x(
    torpedo_megacredits: int,
    count: int = 1,
) -> int:
    """Scaled score delta for torpedoes loaded onto ships.

    Ammo always costs 1 KT each of tritanium, duranium, and molybdenum regardless of
    torpedo type (launcher mineral columns on the catalog row are not used here).
    """
    return 2 * construction_value(torpedo_megacredits, LOADED_TORPEDO_AMMO_MINERALS) * count


def starbase_fighter_score_delta_2x(count: int = 1) -> int:
    """Scaled score delta for starbase fighters (half military value)."""
    return STARBASE_FIGHTER_SCORE_DELTA_2X * count


def starbase_defense_post_score_delta_2x(count: int = 1) -> int:
    """Scaled score delta for starbase defense posts (half military value)."""
    return STARBASE_DEFENSE_POST_SCORE_DELTA_2X * count


def planet_defense_post_score_delta_2x(count: int = 1) -> int:
    """Scaled score delta for planetary defense posts (half military value)."""
    return PLANET_DEFENSE_POST_SCORE_DELTA_2X * count
