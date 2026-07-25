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
        settings.hwdistribution == HW_DISTRIBUTION_CIRCULAR
        and settings.mapshape == MAP_SHAPE_ROUND
    )
