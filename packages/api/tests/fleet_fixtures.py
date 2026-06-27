"""Shared helpers for fleet analytic tests."""

from __future__ import annotations

import json
from pathlib import Path

from api.analytics.fleet.types import FleetAcquisitionLedger, FleetTurnSnapshot
from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def single_ship_turn(
    *,
    turn_number: int,
    ship_id: int,
    owner_id: int,
    x: int,
    y: int,
    hull_id: int = 13,
    engine_id: int = 9,
    beam_id: int = 3,
    torpedoid: int = 6,
) -> TurnInfo:
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_data = json.load(handle)
    turn_data["settings"]["turn"] = turn_number
    turn_data["game"]["turn"] = turn_number
    turn_data["ships"] = [
        {
            "friendlycode": "tst",
            "name": "Test Ship",
            "warp": 9,
            "x": x,
            "y": y,
            "beams": 8,
            "bays": 6,
            "torps": 6,
            "mission": 0,
            "mission1target": 0,
            "mission2target": 0,
            "enemy": 0,
            "damage": 0,
            "crew": 100,
            "clans": 0,
            "neutronium": 0,
            "tritanium": 0,
            "duranium": 0,
            "molybdenum": 0,
            "supplies": 0,
            "ammo": 0,
            "megacredits": 0,
            "transferclans": 0,
            "transferneutronium": 0,
            "transferduranium": 0,
            "transfertritanium": 0,
            "transfermolybdenum": 0,
            "transfersupplies": 0,
            "transferammo": 0,
            "transfermegacredits": 0,
            "transfertargetid": 0,
            "transfertargettype": 0,
            "targetx": x,
            "targety": y,
            "mass": 100,
            "heading": 0,
            "turn": 1,
            "turnkilled": 0,
            "beamid": beam_id,
            "engineid": engine_id,
            "hullid": hull_id,
            "ownerid": owner_id,
            "torpedoid": torpedoid,
            "experience": 0,
            "infoturn": turn_number,
            "podhullid": 0,
            "podcargo": 0,
            "goal": 0,
            "goaltarget": 0,
            "goaltarget2": 0,
            "waypoints": [],
            "history": [],
            "iscloaked": False,
            "readystatus": 0,
            "id": ship_id,
        }
    ]
    return turn_info_from_json(turn_data)


def ledger_for_player(snapshot: FleetTurnSnapshot, player_id: int) -> FleetAcquisitionLedger:
    for ledger in snapshot.players:
        if ledger.player_id == player_id:
            return ledger
    raise AssertionError(f"missing player ledger {player_id}")
