"""Shared options for Core turn analytics."""

from dataclasses import dataclass

from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.transport.connections_options import FlareConnectionMode


@dataclass(frozen=True)
class TurnAnalyticsOptions:
    connection_warp_speed: int | None = None
    connection_gravitonic_movement: bool = False
    connection_flare_mode: FlareConnectionMode | str = FlareConnectionMode.OFF
    connection_flare_depth: int = 1
    connection_include_illustrative_routes: bool = False
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS
