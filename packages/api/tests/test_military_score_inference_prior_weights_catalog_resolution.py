"""Integration tests for prior-weights catalog resolution and combo weighting."""

from dataclasses import replace

import pytest
from api.analytics.military_score_inference.aggregate_action_registry import (
    PLANET_DEFENSE_POST_BIN_BOUNDS,
    SHIP_TORPEDO_BIN_BOUNDS,
    iter_aggregate_action_slots,
)
from api.analytics.military_score_inference.hull_category import INFERENCE_HULL_CATEGORIES
from api.analytics.military_score_inference.inference_game_category import (
    STANDARD_INFERENCE_GAME_CATEGORY,
)
from api.analytics.military_score_inference.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)
from api.analytics.military_score_inference.prior_weights_asset import (
    load_prior_weights_for_category,
)
from api.analytics.military_score_inference.prior_weights_catalog import (
    ResolvedComponentCountTables,
)
from api.analytics.military_score_inference.prior_weights_laplace import (
    IMPLICIT_UNIFORM_PSEUDO_COUNT,
    LEGACY_PARSIMONY_OCCURRENCE_PENALTY,
    counts_to_log_weights,
    none_bin_pseudo_count,
)
from api.analytics.military_score_inference.prior_weights_resolve import (
    resolve_prior_weights_catalog,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.models.components import Beam, Engine, Torpedo

from tests.fixtures.military_score_inference import _observation
from tests.fixtures.military_score_inference_prior_weights import (
    beam_ship_hull,
    minimal_prior_catalog,
    torpedo_hull,
)


def test_wildcard_expands_unlisted_buildable_hull(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({15, 24, 99}),
        eligible_engine_ids=frozenset({1, 5}),
        eligible_beam_ids=frozenset({1, 3}),
        eligible_torp_ids=frozenset({1, 8}),
    )
    assert catalog.hull_marginal_log_weight(99, default_weight=-1) != -1
    assert catalog.hull_marginal_log_weight(24) > catalog.hull_marginal_log_weight(99)


def test_true_freighter_hull_counts_collapse_to_generic_solver_combo(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({15, 24}),
        generic_freighter_hull_ids=frozenset({15}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({1}),
        eligible_torp_ids=frozenset({1}),
    )
    expected_weights = counts_to_log_weights(
        {24: 450.0, "generic_freighter": 220.0},
        scale=INFERENCE_PROBABILITY_WEIGHT_SCALE,
    )

    assert catalog.hull_marginal_log_weight(24) == expected_weights[24]
    assert catalog.hull_marginal_log_weight(15, default_weight=-1) == -1
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
        )
        == expected_weights["generic_freighter"]
    )


def test_missing_component_subtable_uses_uniform_distribution(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({65}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({2, 3}),
        eligible_torp_ids=frozenset({1, 8}),
    )
    hull = torpedo_hull()
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
    beam_two = Beam(
        id=2,
        name="X-Ray",
        cost=2,
        tritanium=1,
        duranium=0,
        molybdenum=1,
        mass=1,
        techlevel=1,
        crewkill=15,
        damage=4,
    )
    beam_three = Beam(
        id=3,
        name="Plasma Bolt",
        cost=3,
        tritanium=1,
        duranium=1,
        molybdenum=0,
        mass=2,
        techlevel=2,
        crewkill=20,
        damage=6,
    )
    torpedo_common = Torpedo(
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

    with_beam_two = catalog.combo_probability_weight(
        combo_id="combo_beam_two",
        hull=hull,
        engine=engine,
        beam=beam_two,
        torpedo=torpedo_common,
        beam_count=1,
        launcher_count=2,
    )
    with_beam_three = catalog.combo_probability_weight(
        combo_id="combo_beam_three",
        hull=hull,
        engine=engine,
        beam=beam_three,
        torpedo=torpedo_common,
        beam_count=1,
        launcher_count=2,
    )
    single_beam_catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({65}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({2}),
        eligible_torp_ids=frozenset({1, 8}),
    )
    with_single_beam_universe = single_beam_catalog.combo_probability_weight(
        combo_id="combo_single_beam_universe",
        hull=hull,
        engine=engine,
        beam=beam_two,
        torpedo=torpedo_common,
        beam_count=1,
        launcher_count=2,
    )

    expected_uniform_weight = counts_to_log_weights(
        {2: 1.0, 3: 1.0}, scale=INFERENCE_PROBABILITY_WEIGHT_SCALE
    )[2]

    assert with_beam_two == with_beam_three
    assert with_beam_two - with_single_beam_universe == expected_uniform_weight
    assert expected_uniform_weight < 0


def test_resolve_prior_weights_catalog_rejects_all_empty_eligibility_universes(sample_turn):
    with pytest.raises(ValueError, match="at least one non-empty eligibility universe"):
        resolve_prior_weights_catalog(
            _observation(),
            replace(sample_turn.settings, endturn=100, shiplimit=200),
            buildable_hull_ids=frozenset(),
            eligible_engine_ids=frozenset(),
            eligible_beam_ids=frozenset(),
            eligible_torp_ids=frozenset(),
        )


def test_missing_torpedo_histogram_uses_uniform_distribution(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset(),
        eligible_engine_ids=frozenset(),
        eligible_beam_ids=frozenset(),
        eligible_torp_ids=frozenset({1, 12}),
    )
    # The implicit-uniform path seeds active bins uniformly and the leading none bin
    # via none_bin_pseudo_count, so the missing table keeps the occurrence cost.
    implicit_counts = {0: none_bin_pseudo_count(IMPLICIT_UNIFORM_PSEUDO_COUNT)}
    for index in range(1, len(SHIP_TORPEDO_BIN_BOUNDS)):
        implicit_counts[index] = IMPLICIT_UNIFORM_PSEUDO_COUNT
    expected_implicit_log_weights = counts_to_log_weights(
        implicit_counts,
        scale=INFERENCE_PROBABILITY_WEIGHT_SCALE,
    )
    expected_implicit_weights = tuple(
        expected_implicit_log_weights[index] for index in range(len(SHIP_TORPEDO_BIN_BOUNDS))
    )
    asset_buckets = catalog.probability_buckets_for_action(
        "ship_torps_loaded_1",
        SHIP_TORPEDO_BIN_BOUNDS,
    )
    implicit_buckets = catalog.probability_buckets_for_action(
        "ship_torps_loaded_12",
        SHIP_TORPEDO_BIN_BOUNDS,
    )

    asset_marginals = tuple(bucket.marginal_weight for bucket in asset_buckets)
    implicit_marginals = tuple(bucket.marginal_weight for bucket in implicit_buckets)

    assert implicit_marginals == expected_implicit_weights
    # The none bin is the most likely outcome; the active bins are equal and lower.
    assert implicit_marginals[0] == max(implicit_marginals)
    assert len(set(implicit_marginals[1:])) == 1
    # The gap from the none bin to the active bins reproduces the legacy occurrence cost.
    assert implicit_marginals[0] - implicit_marginals[1] == LEGACY_PARSIMONY_OCCURRENCE_PENALTY
    assert asset_marginals != implicit_marginals


def test_none_bin_seed_reproduces_legacy_parsimony_penalty(sample_turn):
    """The asset 0: seeds make count 0 free and the most likely active bin cost ~ -50."""
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({24}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({1}),
        eligible_torp_ids=frozenset({1}),
    )
    buckets = catalog.probability_buckets_for_action(
        "planet_defense_posts_added_total",
        PLANET_DEFENSE_POST_BIN_BOUNDS,
    )
    weights = [bucket.marginal_weight for bucket in buckets]
    none_weight = weights[0]
    best_active_weight = max(weights[1:])

    # The none bin is the max-weight bin, so choosing count 0 costs nothing.
    assert none_weight == max(weights)
    # The gap from the none bin to the most likely active bin reproduces parsimony.
    assert abs((none_weight - best_active_weight) - LEGACY_PARSIMONY_OCCURRENCE_PENALTY) <= 1


def test_standard_asset_occurrence_bins_reproduce_legacy_penalty_for_every_aggregate(sample_turn):
    asset, _, _ = load_prior_weights_for_category(STANDARD_INFERENCE_GAME_CATEGORY)
    observations_by_band = {
        "before_ship_limit": _observation(),
        "after_ship_limit": replace(_observation(), is_after_ship_limit=True),
    }

    for band, observation in observations_by_band.items():
        catalog = resolve_prior_weights_catalog(
            observation,
            replace(sample_turn.settings, endturn=100, shiplimit=200),
            buildable_hull_ids=frozenset({24}),
            eligible_engine_ids=frozenset({1}),
            eligible_beam_ids=frozenset({1}),
            eligible_torp_ids=frozenset(range(1, 12)),
        )

        for slot in iter_aggregate_action_slots(eligible_torp_ids=frozenset(range(1, 12))):
            histogram = asset.aggregates[band][slot.action_id].histogram
            assert 0 in histogram

            buckets = catalog.probability_buckets_for_action(slot.action_id, slot.spec.bin_bounds)
            weights = [bucket.marginal_weight for bucket in buckets]
            none_weight = weights[0]
            best_active_weight = max(weights[1:])

            assert none_weight == max(weights)
            assert (
                abs((none_weight - best_active_weight) - LEGACY_PARSIMONY_OCCURRENCE_PENALTY) <= 1
            )


def test_combo_probability_weight_rejects_missing_hull_prior():
    catalog = minimal_prior_catalog(hull_log_weights={})
    hull = beam_ship_hull()

    with pytest.raises(ValueError, match="missing hull marginal weight"):
        catalog.combo_probability_weight(
            combo_id="combo_missing_hull",
            hull=hull,
            engine=_engine(1),
            beam=_beam(1),
            torpedo=None,
            beam_count=hull.beams,
            launcher_count=0,
        )


def test_combo_probability_weight_rejects_missing_component_prior():
    catalog = minimal_prior_catalog(hull_log_weights={24: 0})
    component_tables = {
        category: ResolvedComponentCountTables(
            engines={},
            beams={},
            torpedoes={},
            slot_fill={},
        )
        for category in INFERENCE_HULL_CATEGORIES
    }
    catalog = replace(catalog, _component_tables=component_tables)
    hull = beam_ship_hull()

    with pytest.raises(ValueError, match="missing beam_ship.engines weight"):
        catalog.combo_probability_weight(
            combo_id="combo_missing_engine",
            hull=hull,
            engine=_engine(1),
            beam=_beam(1),
            torpedo=None,
            beam_count=hull.beams,
            launcher_count=0,
        )


def _engine(engine_id: int) -> Engine:
    return Engine(
        id=engine_id,
        name=f"Engine {engine_id}",
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


def _beam(beam_id: int) -> Beam:
    return Beam(
        id=beam_id,
        name=f"Beam {beam_id}",
        cost=1,
        tritanium=1,
        duranium=0,
        molybdenum=0,
        mass=1,
        techlevel=1,
        crewkill=10,
        damage=3,
    )


def test_combo_probability_weight_differs_by_component_likelihood(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        race_id=1,
        buildable_hull_ids=frozenset({24}),
        eligible_engine_ids=frozenset({1, 5}),
        eligible_beam_ids=frozenset({1}),
        eligible_torp_ids=frozenset({1, 8}),
    )
    hull = beam_ship_hull()
    engine_common = Engine(
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
    engine_rare = replace(engine_common, id=5, name="Rare Drive")
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

    likely = catalog.combo_probability_weight(
        combo_id="combo_likely",
        hull=hull,
        engine=engine_common,
        beam=beam,
        torpedo=None,
        beam_count=hull.beams,
        launcher_count=0,
    )
    unlikely = catalog.combo_probability_weight(
        combo_id="combo_unlikely",
        hull=hull,
        engine=engine_rare,
        beam=beam,
        torpedo=None,
        beam_count=1,
        launcher_count=0,
    )
    assert likely != unlikely
    assert likely > unlikely
