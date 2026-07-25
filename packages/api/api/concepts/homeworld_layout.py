"""Host-aligned homeworld map-gen layout constants.

Neighborhood LY bands and Starmap distribution / map-shape codes used by the
homeworld locator. Not race-specific (see ``races.py`` for climate).
"""

from __future__ import annotations

from api.models.game import GameSettings

# Map-gen neighborhood bands around each homeworld (Nu Starmap customization).
VERY_CLOSE_PLANETS_MAX_LY = 81.0
CLOSE_PLANETS_MAX_LY = 162.0

# GameSettings.hwdistribution
HW_DISTRIBUTION_RANDOM_SPACED = 1
HW_DISTRIBUTION_CIRCULAR = 2
HW_DISTRIBUTION_LEFT_AND_RIGHT = 3
HW_DISTRIBUTION_ONE_VS_CIRCLE = 4

# GameSettings.mapshape
MAP_SHAPE_ROUND = 0
MAP_SHAPE_RECTANGULAR = 1
MAP_SHAPE_IRREGULAR_ROUND = 2

# Classical Nu universe origin used when planet cloud is too sparse for a bbox center.
DEFAULT_MAP_CENTER_XY = (2000.0, 2000.0)


def supports_circular_round_candidate_geometry(settings: GameSettings) -> bool:
    """True when v1 ring/sector homeworld candidate geometry applies."""
    return (
        settings.hwdistribution == HW_DISTRIBUTION_CIRCULAR and settings.mapshape == MAP_SHAPE_ROUND
    )


INACTIVE_REASON_NO_HOMEWORLD = "nohomeworld"
INACTIVE_REASON_WANDERING_TRIBES = "wandering_tribes"
# Named Nu recipes (Ashes / Crazy Intermix / Disunited Kingdoms) have no scenario
# name field on GameSettings -- detect via recipe-shaped knobs below.
INACTIVE_REASON_SCENARIO_OVERRIDE = "scenario_override"


def _has_scenario_override_recipe(settings: GameSettings) -> bool:
    """True for recipe-shaped settings that design treats as inactive.

    Precedence among recipes is not exposed -- all map to
    ``INACTIVE_REASON_SCENARIO_OVERRIDE``. Ashes is ``hwdistribution == 4``;
    Crazy Intermix / Disunited Kingdoms use ``extraplanets`` with / without
    ``extraplanetsrandomloc``. Private games can set the same knobs without the
    UI recipe name; that is an accepted product-gate false positive.
    """
    if settings.hwdistribution == HW_DISTRIBUTION_ONE_VS_CIRCLE:
        return True
    if settings.extraplanets > 0:
        return True
    return False


def homeworld_locator_inactive_reason(settings: GameSettings) -> str | None:
    """Return an inactive reason when traditional homeworld planets do not exist.

    ``None`` means the homeworld locator may run. Precedence: ``nohomeworld``,
    Wandering Tribes, then scenario-recipe heuristics (Ashes / Crazy Intermix /
    Disunited Kingdoms).
    """
    if settings.nohomeworld:
        return INACTIVE_REASON_NO_HOMEWORLD
    if settings.wanderingtribescount > 0:
        return INACTIVE_REASON_WANDERING_TRIBES
    if _has_scenario_override_recipe(settings):
        return INACTIVE_REASON_SCENARIO_OVERRIDE
    return None


def is_homeworld_locator_available(settings: GameSettings) -> bool:
    """True when the homeworld locator can run for these game settings."""
    return homeworld_locator_inactive_reason(settings) is None


# Settings fields that, when changed on GameInfo refresh, invalidate inferred
# homeworld locator game-global state (user-asserted rows are preserved separately).
HOMEWORLD_RELEVANT_SETTINGS_FIELDS: tuple[str, ...] = (
    "nohomeworld",
    "wanderingtribescount",
    "hwdistribution",
    "extraplanets",
    "extraplanetsrandomloc",
    "mapshape",
    "mapwidth",
    "mapheight",
    "verycloseplanets",
    "closeplanets",
    "otherplanetsminhomeworlddist",
    "homeworldhasstarbase",
    "homeworldclans",
    "shuffleteampositions",
    "fixedstartpositions",
)


def homeworld_settings_fingerprint(settings: GameSettings) -> tuple[object, ...]:
    """Stable fingerprint of homeworld-relevant GameSettings fields."""
    return tuple(getattr(settings, field) for field in HOMEWORLD_RELEVANT_SETTINGS_FIELDS)
