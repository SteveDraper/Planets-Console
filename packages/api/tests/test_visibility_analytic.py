"""Tests for Visibility analytic coverage origins and map payload."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.visibility import ANALYTIC_ID, get_visibility_map
from api.concepts.ship_missions import MINE_SWEEP_MISSION, SENSOR_SWEEP_MISSION
from api.concepts.visibility_coverage import (
    KIND_ACTIVE_MINEFIELD_DETECT,
    KIND_ACTIVE_SENSOR_SWEEP,
    KIND_POTENTIAL_MINEFIELD_DETECT,
    KIND_POTENTIAL_SENSOR_SWEEP,
    KIND_SHIP_SCAN,
    active_minefield_detect_origins,
    active_sensor_sweep_origins,
    potential_minefield_detect_origins,
    potential_sensor_sweep_origins,
    ship_scan_origins,
    visibility_owner_ids,
)
from api.models.components import Hull
from api.models.player import Relation
from api.models.ship import Ship
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as f:
        return turn_info_from_json(json.load(f))


@pytest.fixture
def stellar_cartography_turn():
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        return turn_info_from_json(json.load(f))


def _hull(*, hull_id: int, special: str = "") -> Hull:
    return Hull(
        id=hull_id,
        name=f"Hull {hull_id}",
        tritanium=0,
        duranium=0,
        molybdenum=0,
        fueltank=0,
        crew=0,
        engines=1,
        mass=0,
        techlevel=1,
        cargo=0,
        fighterbays=0,
        launchers=0,
        beams=0,
        cancloak=False,
        cost=0,
        special=special,
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def test_visibility_owner_ids_includes_share_intel_partners(sample_turn):
    viewpoint = sample_turn.player.id
    # Baseline sample has no Share Intel partners.
    assert visibility_owner_ids(viewpoint, sample_turn.relations) == frozenset({viewpoint})

    relations = list(sample_turn.relations)
    relations[0] = replace(relations[0], relationto=3, relationfrom=1)
    owners = visibility_owner_ids(viewpoint, relations)
    assert owners == frozenset({viewpoint, relations[0].playertoid})


def test_ship_scan_origins_planets_and_ships_only(sample_turn):
    owners = frozenset({sample_turn.player.id})
    origins = ship_scan_origins(
        sample_turn.planets,
        sample_turn.ships,
        sample_turn.hulls,
        owners,
        ship_scan_range=300,
    )
    owned_planets = [p for p in sample_turn.planets if p.ownerid in owners]
    owned_ships = [s for s in sample_turn.ships if s.ownerid in owners]
    assert len(origins) == len(owned_planets) + len(owned_ships)
    assert all(o.base_range == 300 for o in origins)


def _ship(
    *,
    ship_id: int,
    ownerid: int,
    hullid: int,
    mission: int,
    x: int,
    y: int,
) -> Ship:
    return Ship(
        id=ship_id,
        friendlycode="aaa",
        name=f"S{ship_id}",
        warp=0,
        x=x,
        y=y,
        beams=0,
        bays=0,
        torps=0,
        mission=mission,
        mission1target=0,
        mission2target=0,
        enemy=0,
        damage=0,
        crew=0,
        clans=0,
        neutronium=0,
        tritanium=0,
        duranium=0,
        molybdenum=0,
        supplies=0,
        ammo=0,
        megacredits=0,
        transferclans=0,
        transferneutronium=0,
        transferduranium=0,
        transfertritanium=0,
        transfermolybdenum=0,
        transfersupplies=0,
        transferammo=0,
        transfermegacredits=0,
        transfertargetid=0,
        transfertargettype=0,
        targetx=x,
        targety=y,
        mass=100,
        heading=0,
        turn=1,
        turnkilled=0,
        beamid=0,
        engineid=1,
        hullid=hullid,
        ownerid=ownerid,
        torpedoid=0,
        experience=0,
        infoturn=1,
        podhullid=0,
        podcargo=0,
        goal=0,
        goaltarget=0,
        goaltarget2=0,
    )


def test_active_vs_potential_sensor_sweep_origins():
    hulls = [
        _hull(hull_id=1),
        _hull(hull_id=9, special="Bioscan - Will detect 20%"),
        _hull(hull_id=27, special="Nebula Scanner - up to 100ly"),
    ]
    ships = [
        _ship(ship_id=1, ownerid=8, hullid=1, mission=0, x=10, y=10),
        _ship(ship_id=2, ownerid=8, hullid=9, mission=SENSOR_SWEEP_MISSION, x=20, y=20),
        _ship(ship_id=3, ownerid=8, hullid=27, mission=SENSOR_SWEEP_MISSION, x=30, y=30),
        _ship(ship_id=4, ownerid=2, hullid=1, mission=SENSOR_SWEEP_MISSION, x=40, y=40),
    ]
    owners = frozenset({8})
    active = active_sensor_sweep_origins(ships, hulls, owners, sensor_mission_range=200)
    potential = potential_sensor_sweep_origins(ships, hulls, owners, sensor_mission_range=200)
    assert len(active) == 2
    assert {(o.x, o.y) for o in active} == {(20, 20), (30, 30)}
    assert any(o.has_nebula_scanner for o in active)
    assert len(potential) == 3
    assert all(o.base_range == 200 for o in potential)


def test_active_vs_potential_minefield_detect_origins():
    hulls = [_hull(hull_id=1), _hull(hull_id=27, special="Nebula Scanner - up to 100ly")]
    ships = [
        _ship(ship_id=1, ownerid=8, hullid=1, mission=0, x=10, y=10),
        _ship(ship_id=2, ownerid=8, hullid=27, mission=MINE_SWEEP_MISSION, x=20, y=20),
        _ship(ship_id=3, ownerid=2, hullid=1, mission=MINE_SWEEP_MISSION, x=40, y=40),
    ]
    owners = frozenset({8})
    active = active_minefield_detect_origins(ships, hulls, owners, minefield_detect_range=200)
    potential = potential_minefield_detect_origins(ships, hulls, owners, minefield_detect_range=200)
    assert len(active) == 1
    assert active[0].x == 20 and active[0].y == 20
    assert active[0].has_nebula_scanner is False
    assert len(potential) == 2
    assert all(o.base_range == 200 for o in potential)
    assert all(o.has_nebula_scanner is False for o in potential)


def test_visibility_map_emits_kinds_for_sample_turn(sample_turn):
    # Put ships on Sensor Sweep and Mine Sweep so active kinds are non-empty.
    ships = list(sample_turn.ships)
    owned = [s for s in ships if s.ownerid == sample_turn.player.id]
    assert len(owned) >= 2
    ships[ships.index(owned[0])] = replace(owned[0], mission=SENSOR_SWEEP_MISSION)
    ships[ships.index(owned[1])] = replace(owned[1], mission=MINE_SWEEP_MISSION)
    turn = replace(sample_turn, ships=ships)

    data = get_visibility_map(turn, TurnAnalyticsOptions())
    assert data["analyticId"] == ANALYTIC_ID
    kinds = [o["kind"] for o in data["regionOverlays"]]
    assert KIND_SHIP_SCAN in kinds
    assert KIND_POTENTIAL_SENSOR_SWEEP in kinds
    assert KIND_ACTIVE_SENSOR_SWEEP in kinds
    assert KIND_POTENTIAL_MINEFIELD_DETECT in kinds
    assert KIND_ACTIVE_MINEFIELD_DETECT in kinds
    assert kinds.index(KIND_SHIP_SCAN) < kinds.index(KIND_POTENTIAL_SENSOR_SWEEP)
    assert kinds.index(KIND_POTENTIAL_SENSOR_SWEEP) < kinds.index(KIND_POTENTIAL_MINEFIELD_DETECT)
    assert kinds.index(KIND_POTENTIAL_MINEFIELD_DETECT) < kinds.index(KIND_ACTIVE_SENSOR_SWEEP)
    assert kinds.index(KIND_ACTIVE_SENSOR_SWEEP) < kinds.index(KIND_ACTIVE_MINEFIELD_DETECT)


def test_visibility_map_nebula_patches_when_present(stellar_cartography_turn):
    data = get_visibility_map(stellar_cartography_turn, TurnAnalyticsOptions())
    ship_scan = next(o for o in data["regionOverlays"] if o["kind"] == KIND_SHIP_SCAN)
    assert len(ship_scan["disks"]) >= 1
    # Stellar cartography sample has nebulas; owned origins near them yield patches.
    assert isinstance(ship_scan["patches"], list)

    mine_potential = next(
        o for o in data["regionOverlays"] if o["kind"] == KIND_POTENTIAL_MINEFIELD_DETECT
    )
    # Minefield detect ignores nebulae: disks only.
    assert len(mine_potential["disks"]) >= 1
    assert mine_potential["patches"] == []


def test_visibility_includes_partner_ship_as_origin(sample_turn):
    partner_id = 4
    relations = [
        Relation(
            id=1,
            playerid=sample_turn.player.id,
            playertoid=partner_id,
            relationto=3,
            relationfrom=3,
            conflictlevel=0,
            color="",
        )
    ]
    turn = replace(sample_turn, relations=relations)
    owners = visibility_owner_ids(turn.player.id, turn.relations)
    assert partner_id in owners
    origins = ship_scan_origins(
        turn.planets,
        turn.ships,
        turn.hulls,
        owners,
        ship_scan_range=float(turn.settings.shipscanrange),
    )
    partner_ships = [s for s in turn.ships if s.ownerid == partner_id]
    assert partner_ships
    assert any(o.x == partner_ships[0].x and o.y == partner_ships[0].y for o in origins)
