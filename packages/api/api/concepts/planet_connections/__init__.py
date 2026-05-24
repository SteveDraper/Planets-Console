"""Planet-to-planet travel reachability for one turn (warp, normal wells, optional flares).

Public API: :mod:`api.concepts.planet_connections.connection_engine`.
Other modules in this package are implementation details.
"""

from __future__ import annotations

from api.concepts.planet_connections.connection_engine import (
    ConnectionRoutesOutcome,
    connection_routes_for_planets,
    connection_routes_with_options,
)

__all__ = [
    "ConnectionRoutesOutcome",
    "connection_routes_for_planets",
    "connection_routes_with_options",
]
