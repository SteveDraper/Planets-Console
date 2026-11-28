"""One stored game turn, as the turn-stored hook reports it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnWrite:
    """Turn ``turn_number`` of ``game_id`` was stored for player ``perspective``."""

    game_id: int
    perspective: int
    turn_number: int
