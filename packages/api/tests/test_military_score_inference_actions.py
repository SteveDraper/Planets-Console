"""Tests for military score inference action catalog generation."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.military_score_inference.actions import (
    ActionCatalogConfig,
    _residual_count_bound,
    build_action_catalog,
    build_action_catalog_from_turn,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.component_eligibility import (
    buildable_hull_ids_for_player,
)
from api.analytics.military_score_inference.scoring import (
    STARBASE_FIGHTER_SCORE_DELTA_2X,
    ship_construction_score_delta_2x,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.concepts.races import evil_empire_free_starbase_fighters_per_host_turn
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json

from tests.fixtures.military_score_inference import _observation
from tests.inference_corpus.fixtures import load_turn_fixture

REPO_ROOT = Path(__file__).resolve().parents[3]
EE_TURN_PATH = REPO_ROOT / ".data" / "games" / "628580" / "8" / "turns" / "3.json"
P5_TURN6_PATH = REPO_ROOT / ".data" / "games" / "628580" / "5" / "turns" / "6.json"
GAME_INFO_PATH = REPO_ROOT / ".data" / "games" / "628580" / "info.json"


def test_generated_actions_have_finite_bounds(synthetic_catalog_context):
    catalog = build_action_catalog(
        _observation(),
        config=ActionCatalogConfig(max_fighter_transfers=10),
        **synthetic_catalog_context,
    )

    assert catalog.catalog_size > 0
    for action in catalog.aggregate_actions:
        assert action.lower_bound >= 0
        assert action.upper_bound >= action.lower_bound
        assert action.upper_bound < 10_000
    for combo in catalog.ship_build_combos:
        assert combo.lower_bound >= 0
        assert combo.upper_bound >= combo.lower_bound
        assert combo.upper_bound < 10_000


def test_noisy_actions_are_aggregate_actions(synthetic_catalog_context):
    catalog = build_action_catalog(_observation(), **synthetic_catalog_context)
    aggregate_actions = [
        action
        for action in catalog.aggregate_actions
        if action.id.endswith("_total") or action.id.startswith("ship_torps_loaded_")
    ]

    assert aggregate_actions
    for action in aggregate_actions:
        assert "planet" in action.id or "starbase" in action.id or "ship_" in action.id


def test_ship_build_combos_respect_observed_count_deltas(synthetic_catalog_context):
    catalog = build_action_catalog(
        _observation(warship_delta=2, freighter_delta=1, starbases_owned=5),
        **synthetic_catalog_context,
    )

    warship_builds = [combo for combo in catalog.ship_build_combos if combo.warship_delta == 1]
    freighter_builds = [combo for combo in catalog.ship_build_combos if combo.freighter_delta == 1]

    assert warship_builds
    assert freighter_builds
    assert all(combo.upper_bound <= 2 for combo in warship_builds)
    assert all(combo.upper_bound <= 1 for combo in freighter_builds)
    assert all(combo.build_slot_usage == 1 for combo in warship_builds + freighter_builds)


@pytest.mark.parametrize(
    ("military_delta_2x", "score_delta_2x", "configured_cap", "expected"),
    [
        (500, 125, 100, 4),
        (500, -125, 100, 4),
        (-500, 125, 100, 4),
        (-500, -125, 100, 4),
        (10, 125, 100, 0),
        (500, 125, 3, 3),
    ],
)
def test_residual_count_bound_uses_abs_residual_regardless_of_sign(
    military_delta_2x,
    score_delta_2x,
    configured_cap,
    expected,
):
    observation = _observation(military_delta_2x=military_delta_2x)
    assert _residual_count_bound(observation, score_delta_2x, configured_cap) == expected


def test_residual_count_bound_applies_scoreboard_partition_slack():
    from api.analytics.military_score_inference.accelerated_start import (
        SCOREBOARD_MILITARY_PARTITION_SLACK_2X,
    )
    from api.analytics.military_score_inference.scoring import STARBASE_FIGHTER_SCORE_DELTA_2X

    observation = _observation(
        military_delta_2x=624,
        military_partition_slack_2x=SCOREBOARD_MILITARY_PARTITION_SLACK_2X,
    )
    assert (
        _residual_count_bound(
            observation,
            STARBASE_FIGHTER_SCORE_DELTA_2X,
            100,
        )
        == 5
    )


def test_negative_fighter_transfer_cannot_create_unbounded_cancellation_loops():
    config = ActionCatalogConfig(max_fighter_transfers=7)
    full_step = resolve_tier_policies()[-1]
    catalog = build_action_catalog(
        _observation(military_delta_2x=500),
        hulls_by_id={},
        engines_by_id={},
        beams_by_id={},
        torpedos_by_id={},
        buildable_hull_ids=frozenset(),
        eligible_engine_ids=frozenset(),
        eligible_beam_ids=frozenset(),
        eligible_torp_ids=frozenset(),
        config=config,
        policy_step=full_step,
    )

    negative_transfer = next(
        action for action in catalog.aggregate_actions if action.id == "fighters_ship_to_starbase"
    )
    positive_transfer = next(
        action for action in catalog.aggregate_actions if action.id == "fighters_starbase_to_ship"
    )

    assert negative_transfer.score_delta_2x == -STARBASE_FIGHTER_SCORE_DELTA_2X
    assert negative_transfer.upper_bound <= config.max_fighter_transfers
    assert positive_transfer.upper_bound <= config.max_fighter_transfers
    assert negative_transfer.upper_bound == 500 // STARBASE_FIGHTER_SCORE_DELTA_2X


def test_catalog_size_exposed_in_diagnostics(synthetic_catalog_context):
    catalog = build_action_catalog(_observation(), **synthetic_catalog_context)

    diagnostics = catalog.diagnostics()
    assert diagnostics["catalog_size"] == catalog.catalog_size
    assert diagnostics["catalog_size"] == len(catalog.aggregate_actions) + len(
        catalog.ship_build_combos
    )
    assert diagnostics["ship_build_combo_count"] == len(catalog.ship_build_combos)


def test_ship_build_combos_exclude_build_time_ammo(synthetic_catalog_context):
    catalog = build_action_catalog(_observation(), **synthetic_catalog_context)
    combo_ids = {combo.combo_id for combo in catalog.ship_build_combos}

    assert not any("fighters" in combo_id for combo_id in combo_ids)

    carrier_empty = next(
        combo
        for combo in catalog.ship_build_combos
        if combo.hull_id == 71 and combo.beam_count == 0 and combo.launcher_count == 0
    )
    hull = synthetic_catalog_context["hulls_by_id"][71]
    engine = synthetic_catalog_context["engines_by_id"][1]
    expected_score = ship_construction_score_delta_2x(
        hull.cost + engine.cost * hull.engines,
        hull.tritanium
        + hull.duranium
        + hull.molybdenum
        + (engine.tritanium + engine.duranium + engine.molybdenum) * hull.engines,
    )
    assert carrier_empty.score_delta_2x == expected_score


def test_ship_build_score_scales_engine_cost_by_hull_engine_slots(synthetic_catalog_context):
    catalog = build_action_catalog(
        _observation(warship_delta=1, freighter_delta=1),
        **synthetic_catalog_context,
    )
    carrier_build = next(
        combo
        for combo in catalog.ship_build_combos
        if combo.hull_id == 71 and combo.beam_count == 0 and combo.launcher_count == 0
    )
    hull = synthetic_catalog_context["hulls_by_id"][71]
    engine = synthetic_catalog_context["engines_by_id"][1]
    engine_minerals = engine.tritanium + engine.duranium + engine.molybdenum
    hull_minerals = hull.tritanium + hull.duranium + hull.molybdenum
    expected = ship_construction_score_delta_2x(
        hull.cost + engine.cost * hull.engines,
        hull_minerals + engine_minerals * hull.engines,
    )
    assert carrier_build.score_delta_2x == expected
    assert hull.engines == 2


def test_ship_build_combos_are_not_filtered_by_hull_isbase_flag(synthetic_catalog_context):
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
    assert catalog.ship_build_combos


def test_no_flat_build_preset_actions_remain(synthetic_catalog_context):
    catalog = build_action_catalog(_observation(), **synthetic_catalog_context)
    assert not any(action.id.startswith("build_") for action in catalog.aggregate_actions)


@pytest.mark.skipif(not P5_TURN6_PATH.is_file(), reason="local store only")
def test_buildable_hull_ids_from_turn_racehulls_not_activehulls():
    """Br5 Kaye (45) is in turn.racehulls but not player.activehulls for Privateer."""
    with open(GAME_INFO_PATH) as handle:
        settings_defaults = json.load(handle)["settings"]
    with open(P5_TURN6_PATH) as handle:
        turn = turn_info_from_json(json.load(handle), settings_defaults=settings_defaults)
    buildable_hulls = buildable_hull_ids_for_player(turn, 5)
    assert 45 in buildable_hulls
    assert "45" not in turn.player.activehulls


def test_build_action_catalog_from_turn_sample(sample_turn):
    observation = _observation(
        military_delta_2x=110,
        warship_delta=0,
        freighter_delta=1,
        starbases_owned=10,
    )
    buildable_hulls = buildable_hull_ids_for_player(sample_turn, observation.player_id)
    full_step = resolve_tier_policies()[-1]
    catalog = build_action_catalog_from_turn(observation, sample_turn, policy_step=full_step)

    assert catalog.catalog_size > 0
    assert "planet_defense_posts_added_total" in {action.id for action in catalog.aggregate_actions}
    assert buildable_hulls
    if observation.warship_delta > 0 or observation.freighter_delta > 0:
        catalog_hull_ids = {hull.id for hull in sample_turn.hulls}
        buildable_in_catalog = buildable_hulls & catalog_hull_ids
        if buildable_in_catalog:
            assert catalog.ship_build_combos


@pytest.mark.skipif(not GAME_INFO_PATH.is_file(), reason="local store only")
def test_evil_empire_free_fighters_per_turn_from_game_settings():
    with open(GAME_INFO_PATH) as handle:
        game_info = game_info_from_json(json.load(handle))
    assert evil_empire_free_starbase_fighters_per_host_turn(game_info.settings) == 5


@pytest.mark.skipif(not EE_TURN_PATH.is_file(), reason="local store only")
def test_evil_empire_catalog_includes_likely_free_starbase_fighters():
    with open(GAME_INFO_PATH) as handle:
        settings_defaults = json.load(handle)["settings"]
    with open(EE_TURN_PATH) as handle:
        turn = turn_info_from_json(json.load(handle), settings_defaults=settings_defaults)
    score = next(s for s in turn.scores if s.ownerid == 8)
    observation = build_inference_observation(score, turn)
    catalog = build_action_catalog_from_turn(observation, turn)
    free_action = next(
        (
            action
            for action in catalog.aggregate_actions
            if action.id == "evil_empire_free_starbase_fighters"
        ),
        None,
    )
    assert free_action is not None
    assert free_action.probability_weight == 75
    assert free_action.upper_bound > 0
