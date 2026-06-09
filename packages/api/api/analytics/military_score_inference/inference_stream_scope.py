"""Scope key for a batch of scoreboard inference streams on one turn snapshot."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class InferenceStreamScope:
    game_id: int
    perspective: int
    turn_number: int
