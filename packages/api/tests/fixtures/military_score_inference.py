"""Shared fixtures and helpers for military score inference tests."""

import json
from pathlib import Path

import pytest
from api.analytics.military_score_inference.models import InferenceObservation
from api.models.components import Beam, Engine, Hull, Torpedo
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "api" / "storage" / "assets"


def _observation(
    *,
    military_delta_2x: int = 1100,
    warship_delta: int = 1,
    freighter_delta: int = 0,
    starbases_owned: int = 3,
    military_partition_slack_2x: int = 0,
) -> InferenceObservation:
    return InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=0,
        starbases_owned=starbases_owned,
        is_after_ship_limit=False,
        military_partition_slack_2x=military_partition_slack_2x,
    )


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        return turn_info_from_json(json.load(handle))


@pytest.fixture
def synthetic_catalog_context():
    freighter = Hull(
        id=15,
        name="Small Deep Space Freighter",
        tritanium=2,
        duranium=2,
        molybdenum=3,
        fueltank=100,
        crew=10,
        engines=1,
        mass=10,
        techlevel=1,
        cargo=70,
        fighterbays=0,
        launchers=0,
        beams=0,
        cancloak=False,
        cost=10,
        special="",
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
    warship = Hull(
        id=24,
        name="Serpent Class Escort",
        tritanium=33,
        duranium=15,
        molybdenum=5,
        fueltank=160,
        crew=35,
        engines=1,
        mass=55,
        techlevel=1,
        cargo=20,
        fighterbays=0,
        launchers=0,
        beams=2,
        cancloak=False,
        cost=40,
        special="",
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
    carrier = Hull(
        id=71,
        name="Carrier",
        tritanium=10,
        duranium=10,
        molybdenum=10,
        fueltank=200,
        crew=100,
        engines=2,
        mass=100,
        techlevel=5,
        cargo=50,
        fighterbays=5,
        launchers=0,
        beams=0,
        cancloak=False,
        cost=100,
        special="",
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
    engine = Engine(
        id=1,
        name="Stardrive 1",
        cost=5,
        tritanium=1,
        duranium=1,
        molybdenum=1,
        techlevel=1,
        warp1=50,
        warp2=40,
        warp3=30,
        warp4=20,
        warp5=10,
        warp6=0,
        warp7=0,
        warp8=0,
        warp9=0,
    )
    beam = Beam(
        id=1,
        name="Laser",
        cost=1,
        tritanium=1,
        duranium=0,
        molybdenum=0,
        mass=1,
        techlevel=1,
        crewkill=10,
        damage=3,
    )
    torpedo = Torpedo(
        id=1,
        fullid=1,
        name="Mark 1 Photon",
        torpedocost=1,
        launchercost=1,
        tritanium=1,
        duranium=1,
        molybdenum=0,
        mass=1,
        techlevel=1,
        crewkill=10,
        damage=5,
        combatrange=3,
    )
    return {
        "hulls_by_id": {freighter.id: freighter, warship.id: warship, carrier.id: carrier},
        "engines_by_id": {engine.id: engine},
        "beams_by_id": {beam.id: beam},
        "torpedos_by_id": {torpedo.id: torpedo},
        "buildable_hull_ids": frozenset({freighter.id, warship.id, carrier.id}),
        "eligible_engine_ids": frozenset({engine.id}),
        "eligible_beam_ids": frozenset({beam.id}),
        "eligible_torp_ids": frozenset({torpedo.id}),
    }


@pytest.fixture
def synthetic_catalog_build_context(synthetic_catalog_context):
    from tests.fixtures.military_score_inference_prior_weights import minimal_prior_catalog

    return {
        **synthetic_catalog_context,
        "prior_catalog": minimal_prior_catalog(),
    }
