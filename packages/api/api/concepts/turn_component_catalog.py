"""Turn-scoped component catalog indexes from ``TurnInfo`` snapshots."""

from __future__ import annotations

from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo


def hulls_by_id(turn: TurnInfo) -> dict[int, Hull]:
    return {hull.id: hull for hull in turn.hulls}


def engines_by_id(turn: TurnInfo) -> dict[int, Engine]:
    return {engine.id: engine for engine in turn.engines}


def beams_by_id(turn: TurnInfo) -> dict[int, Beam]:
    return {beam.id: beam for beam in turn.beams}


def torpedos_by_id(turn: TurnInfo) -> dict[int, Torpedo]:
    return {torp.id: torp for torp in turn.torpedos}
