"""Scope key for a multiplexed fleet table NDJSON stream on one turn snapshot."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class FleetTableStreamScope:
    game_id: int
    perspective: int
    turn_number: int
