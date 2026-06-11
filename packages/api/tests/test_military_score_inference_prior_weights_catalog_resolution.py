"""Integration tests for prior-weights catalog resolution and combo weighting."""

from dataclasses import replace

import pytest
from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPEDO_BIN_BOUNDS,
)
from api.analytics.military_score_inference.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)
from api.analytics.military_score_inference.prior_weights_resolve import (
    resolve_prior_weights_catalog,
)
from api.analytics.military_score_inference.prior_weights_laplace import (
    counts_to_log_weights,
    implicit_uniform_component_counts,
)
from api.models.components import Beam, Engine, Torpedo

from tests.fixtures.military_score_inference import _observation
from tests.fixtures.military_score_inference_prior_weights import beam_ship_hull, torpedo_hull


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

    expected_uniform_weight = counts_to_log_weights(
        {2: 1.0, 3: 1.0}, scale=INFERENCE_PROBABILITY_WEIGHT_SCALE
    )[2]
    beam_two_weight = catalog.component_log_weight("torpedo_ship", "beams", 2)
    beam_three_weight = catalog.component_log_weight("torpedo_ship", "beams", 3)

    assert with_beam_two == with_beam_three
    assert beam_two_weight == beam_three_weight == expected_uniform_weight
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
    expected_uniform_weights = tuple(
        counts_to_log_weights(
            implicit_uniform_component_counts(frozenset(range(len(SHIP_TORPEDO_BIN_BOUNDS)))),
            scale=INFERENCE_PROBABILITY_WEIGHT_SCALE,
        )[index]
        for index in range(len(SHIP_TORPEDO_BIN_BOUNDS))
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

    assert implicit_marginals == expected_uniform_weights
    assert len(set(implicit_marginals)) == 1
    assert asset_marginals != implicit_marginals


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
