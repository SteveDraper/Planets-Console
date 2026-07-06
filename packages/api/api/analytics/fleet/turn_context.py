"""Shared read-only turn inputs for per-player fleet materialization."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.fleet.scoreboard_ship_totals import compute_max_ship_id_bound
from api.models.game import TurnInfo


@dataclass(frozen=True)
class FleetTurnContext:
    """Global RST-derived inputs computed once per shell turn."""

    turn: TurnInfo
    max_ship_id_bound: int | None

    @classmethod
    def from_turn(cls, turn: TurnInfo) -> FleetTurnContext:
        return cls(
            turn=turn,
            max_ship_id_bound=compute_max_ship_id_bound(turn),
        )
