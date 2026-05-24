"""Tests for Connections analytic wire contract."""

import pytest
from api.transport.connections_options import (
    DEFAULT_FLARE_DEPTH,
    DEFAULT_WARP_SPEED,
    FLARE_DEPTH_QUERY,
    FLARE_MODE_QUERY,
    GRAVITONIC_MOVEMENT_QUERY,
    INCLUDE_ILLUSTRATIVE_ROUTES_QUERY,
    WARP_SPEED_QUERY,
    FlareConnectionMode,
    derive_include_illustrative_routes,
)


def test_wire_query_names_match_bff_openapi_aliases():
    assert WARP_SPEED_QUERY == "warpSpeed"
    assert GRAVITONIC_MOVEMENT_QUERY == "gravitonicMovement"
    assert FLARE_MODE_QUERY == "flareMode"
    assert FLARE_DEPTH_QUERY == "flareDepth"
    assert INCLUDE_ILLUSTRATIVE_ROUTES_QUERY == "includeIllustrativeRoutes"


def test_flare_connection_mode_wire_values():
    assert FlareConnectionMode.OFF == "off"
    assert FlareConnectionMode.INCLUDE == "include"
    assert FlareConnectionMode.ONLY == "only"


@pytest.mark.parametrize(
    ("flare_mode", "flare_depth", "expected"),
    [
        (FlareConnectionMode.OFF, 1, False),
        (FlareConnectionMode.OFF, 3, False),
        (FlareConnectionMode.INCLUDE, 1, False),
        (FlareConnectionMode.INCLUDE, 2, True),
        (FlareConnectionMode.ONLY, 2, True),
        ("only", 3, True),
    ],
)
def test_derive_include_illustrative_routes(flare_mode, flare_depth, expected):
    assert derive_include_illustrative_routes(flare_mode, flare_depth) is expected


def test_defaults():
    assert DEFAULT_WARP_SPEED == 9
    assert DEFAULT_FLARE_DEPTH == 1
