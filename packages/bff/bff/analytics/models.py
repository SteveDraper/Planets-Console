"""Shared BFF analytics request models."""

from collections.abc import Callable
from dataclasses import dataclass

from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.transport.connections_options import FlareConnectionMode


@dataclass(frozen=True)
class TurnScope:
    game_id: int
    perspective: int
    turn: int


@dataclass(frozen=True)
class ConnectionsMapQuery:
    warp_speed: int
    gravitonic_movement: bool
    flare_mode: FlareConnectionMode
    flare_depth: int
    include_illustrative_routes: bool


CoreAnalyticsLoader = Callable[..., dict]


def load_core_analytic(
    load_core: CoreAnalyticsLoader,
    scope: TurnScope,
    analytic_id: str,
    *,
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
    **kwargs: object,
) -> dict:
    return load_core(
        scope.game_id,
        scope.perspective,
        scope.turn,
        analytic_id,
        diagnostics=diagnostics,
        **kwargs,
    )
