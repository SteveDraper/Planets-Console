"""Tests for military score inference action catalog generation."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.military_score_inference.actions import (
    ActionCatalogConfig,
    build_action_catalog,
    build_action_catalog_from_turn,
    buildable_hull_ids_for_player,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.scoring import (
    STARBASE_FIGHTER_SCORE_DELTA_2X,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _observation(
    *,
    military_delta_2x: int = 1100,
    warship_delta: int = 1,
    freighter_delta: int = 0,
    starbases_owned: int = 3,
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
        "default_engine_id": engine.id,
    }


def test_generated_actions_have_finite_bounds(synthetic_catalog_context):
    catalog = build_action_catalog(
        _observation(),
        config=ActionCatalogConfig(max_fighter_transfers=10),
        **synthetic_catalog_context,
    )

    assert catalog.catalog_size > 0
    for action in catalog.actions:
        assert action.lower_bound >= 0
        assert action.upper_bound >= action.lower_bound
        assert action.upper_bound < 10_000


def test_noisy_actions_are_aggregate_actions(synthetic_catalog_context):
    catalog = build_action_catalog(_observation(), **synthetic_catalog_context)
    aggregate_actions = [
        action
        for action in catalog.actions
        if action.id.endswith("_total") or action.id.startswith("ship_torps_loaded_")
    ]

    assert aggregate_actions
    for action in aggregate_actions:
        assert "planet" in action.id or "starbase" in action.id or "ship_" in action.id


def test_ship_build_actions_respect_observed_count_deltas(synthetic_catalog_context):
    catalog = build_action_catalog(
        _observation(warship_delta=2, freighter_delta=1, starbases_owned=5),
        **synthetic_catalog_context,
    )

    warship_builds = [action for action in catalog.actions if action.warship_delta == 1]
    freighter_builds = [action for action in catalog.actions if action.freighter_delta == 1]

    assert warship_builds
    assert freighter_builds
    assert all(action.upper_bound <= 2 for action in warship_builds)
    assert all(action.upper_bound <= 1 for action in freighter_builds)
    assert all(action.build_slot_usage == 1 for action in warship_builds + freighter_builds)


def test_negative_fighter_transfer_cannot_create_unbounded_cancellation_loops():
    config = ActionCatalogConfig(max_fighter_transfers=7)
    catalog = build_action_catalog(
        _observation(military_delta_2x=500),
        hulls_by_id={},
        engines_by_id={},
        beams_by_id={},
        torpedos_by_id={},
        buildable_hull_ids=frozenset(),
        default_engine_id=None,
        config=config,
    )

    negative_transfer = next(
        action for action in catalog.actions if action.id == "fighters_ship_to_starbase"
    )
    positive_transfer = next(
        action for action in catalog.actions if action.id == "fighters_starbase_to_ship"
    )

    assert negative_transfer.score_delta_2x == -STARBASE_FIGHTER_SCORE_DELTA_2X
    assert negative_transfer.upper_bound <= config.max_fighter_transfers
    assert positive_transfer.upper_bound <= config.max_fighter_transfers
    assert negative_transfer.upper_bound == 500 // STARBASE_FIGHTER_SCORE_DELTA_2X


def test_catalog_size_exposed_in_diagnostics(synthetic_catalog_context):
    catalog = build_action_catalog(_observation(), **synthetic_catalog_context)

    diagnostics = catalog.diagnostics()
    assert diagnostics["catalog_size"] == catalog.catalog_size
    assert diagnostics["catalog_size"] == len(catalog.actions)


def test_ship_build_presets_exclude_build_time_ammo(synthetic_catalog_context):
    catalog = build_action_catalog(_observation(), **synthetic_catalog_context)
    build_action_ids = {action.id for action in catalog.actions if action.id.startswith("build_")}

    assert "build_71_fighters" not in build_action_ids
    assert not any(action_id.endswith("_fighters") for action_id in build_action_ids)

    carrier_empty = next(action for action in catalog.actions if action.id == "build_71_empty")
    hull = synthetic_catalog_context["hulls_by_id"][71]
    engine = synthetic_catalog_context["engines_by_id"][1]
    from api.analytics.military_score_inference.scoring import ship_construction_score_delta_2x

    expected_score = ship_construction_score_delta_2x(
        hull.cost + engine.cost * hull.engines,
        hull.tritanium + hull.duranium + hull.molybdenum
        + (engine.tritanium + engine.duranium + engine.molybdenum) * hull.engines,
    )
    assert carrier_empty.score_delta_2x == expected_score


def test_ship_build_score_scales_engine_cost_by_hull_engine_slots(synthetic_catalog_context):
    catalog = build_action_catalog(
        _observation(warship_delta=1, freighter_delta=1),
        **synthetic_catalog_context,
    )
    carrier_build = next(action for action in catalog.actions if action.id == "build_71_empty")
    hull = synthetic_catalog_context["hulls_by_id"][71]
    engine = synthetic_catalog_context["engines_by_id"][1]
    from api.analytics.military_score_inference.scoring import ship_construction_score_delta_2x

    engine_minerals = engine.tritanium + engine.duranium + engine.molybdenum
    hull_minerals = hull.tritanium + hull.duranium + hull.molybdenum
    expected = ship_construction_score_delta_2x(
        hull.cost + engine.cost * hull.engines,
        hull_minerals + engine_minerals * hull.engines,
    )
    assert carrier_build.score_delta_2x == expected
    assert hull.engines == 2


def test_ship_build_actions_are_not_filtered_by_hull_isbase_flag(synthetic_catalog_context):
    """Planets.nu hull catalog entries use isbase=true for starships too."""
    hulls_by_id = {
        hull_id: replace(hull, isbase=True)
        for hull_id, hull in synthetic_catalog_context["hulls_by_id"].items()
    }
    context = {**synthetic_catalog_context, "hulls_by_id": hulls_by_id}
    catalog = build_action_catalog(
        _observation(warship_delta=1, freighter_delta=0, starbases_owned=3),
        **context,
    )
    ship_build_actions = [action for action in catalog.actions if action.id.startswith("build_")]
    assert ship_build_actions


def test_build_action_catalog_from_turn_sample(sample_turn):
    observation = _observation(
        military_delta_2x=110,
        warship_delta=0,
        freighter_delta=1,
        starbases_owned=10,
    )
    buildable_hulls = buildable_hull_ids_for_player(sample_turn, observation.player_id)
    catalog = build_action_catalog_from_turn(observation, sample_turn)

    assert catalog.catalog_size > 0
    assert "planet_defense_posts_added_total" in {action.id for action in catalog.actions}
    assert buildable_hulls
    ship_build_actions = [action for action in catalog.actions if action.id.startswith("build_")]
    if observation.warship_delta > 0 or observation.freighter_delta > 0:
        catalog_hull_ids = {hull.id for hull in sample_turn.hulls}
        buildable_in_catalog = buildable_hulls & catalog_hull_ids
        if buildable_in_catalog:
            assert ship_build_actions
