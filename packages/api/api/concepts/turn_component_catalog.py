"""Turn-scoped component catalog indexes from ``TurnInfo`` snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo


@dataclass(frozen=True, slots=True)
class TurnComponentIndexes:
    """Hull / engine / beam / torpedo maps for one turn snapshot."""

    hulls_by_id: dict[int, Hull]
    engines_by_id: dict[int, Engine]
    beams_by_id: dict[int, Beam]
    torpedos_by_id: dict[int, Torpedo]


def hulls_by_id(turn: TurnInfo) -> dict[int, Hull]:
    return {hull.id: hull for hull in turn.hulls}


def engines_by_id(turn: TurnInfo) -> dict[int, Engine]:
    return {engine.id: engine for engine in turn.engines}


def beams_by_id(turn: TurnInfo) -> dict[int, Beam]:
    return {beam.id: beam for beam in turn.beams}


def torpedos_by_id(turn: TurnInfo) -> dict[int, Torpedo]:
    return {torp.id: torp for torp in turn.torpedos}


def turn_component_indexes(turn: TurnInfo) -> TurnComponentIndexes:
    """Build all four component indexes once for multi-record wire shaping."""
    return TurnComponentIndexes(
        hulls_by_id=hulls_by_id(turn),
        engines_by_id=engines_by_id(turn),
        beams_by_id=beams_by_id(turn),
        torpedos_by_id=torpedos_by_id(turn),
    )
