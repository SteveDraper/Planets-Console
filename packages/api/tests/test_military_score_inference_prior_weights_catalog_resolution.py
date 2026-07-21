"""Integration tests for prior-weights catalog resolution and combo weighting."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from api.analytics.military_score_inference.aggregate_action_registry import (
    aggregate_bin_bounds_for_action,
    aggregate_bin_bounds_for_spec,
    iter_aggregate_action_slots,
)
from api.analytics.military_score_inference.hull_category import INFERENCE_HULL_CATEGORIES
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
    LEGACY_PARSIMONY_OCCURRENCE_PENALTY,
    counts_to_log_weights,
)
from api.analytics.military_score_inference.prior_weights_resolve import (
    resolve_prior_weights_catalog,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.concepts.game_category import GameCategory
from api.models.components import Beam, Engine, Torpedo

from tests.fixtures.hand_seeded_prior_weights import HAND_SEEDED_PRIOR_WEIGHTS_DIR
from tests.fixtures.military_score_inference import _observation
from tests.fixtures.military_score_inference_prior_weights import (
    beam_ship_hull,
    minimal_prior_catalog,
    torpedo_hull,
)


def test_sparse_hull_table_assigns_implicit_uniform_to_unlisted_buildable_hulls(
    sample_turn,
    tmp_path: Path,
):
    """Mined assets omit wildcard keys; unlisted buildable hulls get implicit uniform mass."""
    from tests.test_military_score_inference_prior_weights_asset import (
        _minimal_prior_weights_document,
    )

    document = _minimal_prior_weights_document(
        hulls={
            "before_ship_limit": {"global": {"beam_ship": {24: 450}}},
            "after_ship_limit": {"global": {"beam_ship": {24: 450}}},
        },
    )
    asset_path = tmp_path / "prior_weights_standard.yaml"
    asset_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({24, 99}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({1}),
        eligible_torp_ids=frozenset({1}),
        base_dir=tmp_path,
    )

    hull_24 = catalog.hull_marginal_log_weight(24, hull_category="beam_ship")
    hull_99 = catalog.hull_marginal_log_weight(99, hull_category="beam_ship")
    assert hull_24 > hull_99


def test_wildcard_expands_unlisted_buildable_hull(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({15, 24, 99}),
        eligible_engine_ids=frozenset({1, 5}),
        eligible_beam_ids=frozenset({1, 3}),
        eligible_torp_ids=frozenset({1, 8}),
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    )
    assert catalog.hull_marginal_log_weight(99, hull_category="beam_ship", default_weight=-1) != -1
    hull_24 = catalog.hull_marginal_log_weight(24, hull_category="beam_ship")
    hull_99 = catalog.hull_marginal_log_weight(99, hull_category="beam_ship")
    assert hull_24 > hull_99


def test_true_freighter_hull_counts_collapse_to_generic_solver_combo(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({15, 24}),
        generic_freighter_hull_ids=frozenset({15}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({1}),
        eligible_torp_ids=frozenset({1}),
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    )
    assert catalog.category_marginal_log_weight("true_freighter") == -179
    assert catalog.hull_marginal_log_weight(24, hull_category="beam_ship") == -11
    assert (
        catalog.hull_marginal_log_weight(15, hull_category="true_freighter", default_weight=-1)
        == -1
    )
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
        )
        == -200
    )


def test_missing_component_subtable_uses_uniform_distribution(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({65}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({2, 3}),
        eligible_torp_ids=frozenset({1, 8}),
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
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
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
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


def test_missing_torpedo_type_uses_pooled_any_torp_histogram(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset(),
        eligible_engine_ids=frozenset(),
        eligible_beam_ids=frozenset(),
        eligible_torp_ids=frozenset({1, 12}),
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    )
    mk1_buckets = catalog.probability_buckets_for_action(
        "ship_torps_loaded_1",
        aggregate_bin_bounds_for_action("ship_torps_loaded_1"),
    )
    mk12_buckets = catalog.probability_buckets_for_action(
        "ship_torps_loaded_12",
        aggregate_bin_bounds_for_action("ship_torps_loaded_12"),
    )

    mk1_marginals = tuple(bucket.marginal_weight for bucket in mk1_buckets)
    mk12_marginals = tuple(bucket.marginal_weight for bucket in mk12_buckets)

    assert mk1_marginals == mk12_marginals


def test_none_bin_seed_reproduces_legacy_parsimony_penalty(sample_turn):
    """The asset 0: seeds make count 0 free and the most likely active bin cost ~ -50."""
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({24}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({1}),
        eligible_torp_ids=frozenset({1}),
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    )
    buckets = catalog.probability_buckets_for_action(
        "planet_defense_posts_added_total",
        aggregate_bin_bounds_for_action("planet_defense_posts_added_total"),
    )
    weights = [bucket.marginal_weight for bucket in buckets]
    none_weight = weights[0]
    best_active_weight = max(weights[1:])

    # The none bin is the max-weight bin, so choosing count 0 costs nothing.
    assert none_weight == max(weights)
    # The gap from the none bin to the most likely active bin reproduces parsimony.
    assert abs((none_weight - best_active_weight) - LEGACY_PARSIMONY_OCCURRENCE_PENALTY) <= 1


def test_standard_asset_occurrence_bins_reproduce_legacy_penalty_for_every_aggregate(sample_turn):
    asset, _, _ = load_prior_weights_for_category(
        GameCategory.STANDARD,
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    )
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
            base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
        )

        for slot in iter_aggregate_action_slots(eligible_torp_ids=frozenset(range(1, 12))):
            histogram = asset.aggregates[band][slot.action_id].histogram
            assert 0 in histogram

            buckets = catalog.probability_buckets_for_action(
                slot.action_id,
                aggregate_bin_bounds_for_spec(slot.spec),
            )
            weights = [bucket.marginal_weight for bucket in buckets]
            none_weight = weights[0]
            best_active_weight = max(weights[1:])

            assert none_weight == max(weights)
            assert (
                abs((none_weight - best_active_weight) - LEGACY_PARSIMONY_OCCURRENCE_PENALTY) <= 1
            )


def test_combo_probability_weight_rejects_missing_hull_prior():
    catalog = minimal_prior_catalog(hull_log_weights_by_category={"beam_ship": {}})
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
    catalog = minimal_prior_catalog(
        hull_log_weights_by_category={"beam_ship": {24: 0}},
    )
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
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
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


def test_federation_halves_partial_slot_fill_penalty():
    from api.concepts.races import SOLAR_FEDERATION_RACE_ID, EVIL_EMPIRE_RACE_ID
    from api.models.components import Engine, Beam
    from tests.fixtures.military_score_inference_prior_weights import (
        beam_ship_hull,
        minimal_prior_catalog,
        _neutral_component_tables,
    )

    tables = {
        category: replace(shell, slot_fill={"full": -2, "partial": -417})
        for category, shell in _neutral_component_tables().items()
    }

    hull = beam_ship_hull()  # 2 beam slots
    engine = Engine(
        id=1,
        name="StarDrive 1",
        cost=1,
        tritanium=1,
        duranium=1,
        molybdenum=1,
        techlevel=1,
        warp1=1,
        warp2=0,
        warp3=0,
        warp4=0,
        warp5=0,
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
        crewkill=1,
        damage=1,
    )
    kwargs = dict(
        hull=hull,
        engine=engine,
        beam=beam,
        torpedo=None,
        beam_count=1,
        launcher_count=0,
    )

    non_fed = minimal_prior_catalog(
        race_id_used=EVIL_EMPIRE_RACE_ID,
        component_tables=tables,
    )
    fed = minimal_prior_catalog(
        race_id_used=SOLAR_FEDERATION_RACE_ID,
        component_tables=tables,
    )
    non_fed_weight = non_fed.combo_probability_weight(combo_id="n", **kwargs)
    fed_weight = fed.combo_probability_weight(combo_id="f", **kwargs)
    # Gap full→partial is -415; Fed uses half (-208) so Fed is 207 less negative.
    assert fed_weight - non_fed_weight == 207

    full_kwargs = {**kwargs, "beam_count": hull.beams}
    assert fed.combo_probability_weight(combo_id="ff", **full_kwargs) == non_fed.combo_probability_weight(
        combo_id="fn", **full_kwargs
    )
