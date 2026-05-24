"""Wire query contract for the Connections turn analytic.

HTTP routers (Core and BFF) and the SPA must use these camelCase query names.
"""

from enum import StrEnum


class FlareConnectionMode(StrEnum):
    """How flare-assisted routes are combined with direct warp-well reachability."""

    OFF = "off"
    INCLUDE = "include"
    ONLY = "only"


WARP_SPEED_QUERY = "warpSpeed"
GRAVITONIC_MOVEMENT_QUERY = "gravitonicMovement"
FLARE_MODE_QUERY = "flareMode"
FLARE_DEPTH_QUERY = "flareDepth"
INCLUDE_ILLUSTRATIVE_ROUTES_QUERY = "includeIllustrativeRoutes"

DEFAULT_WARP_SPEED = 9
DEFAULT_FLARE_DEPTH = 1
MIN_FLARE_DEPTH = 1
MAX_FLARE_DEPTH = 3

FLARE_DEPTH_DESCRIPTION = (
    "Max hops (1–3) for mixed normal-move + flare paths; at least one hop must be a flare. "
    "Larger values add annulus pair candidates. Ignored when flareMode is off."
)

INCLUDE_ILLUSTRATIVE_ROUTES_DESCRIPTION = (
    "When true, flare routes may include per-hop illustrativeRoute steps (Core)."
)


def derive_include_illustrative_routes(
    flare_mode: FlareConnectionMode | str,
    flare_depth: int,
) -> bool:
    """SPA rule: request illustrative hops when flares are on and depth can exceed one."""
    if isinstance(flare_mode, FlareConnectionMode):
        mode = flare_mode
    else:
        mode = FlareConnectionMode(flare_mode)
    return mode is not FlareConnectionMode.OFF and flare_depth >= 2
