"""Tests for inference build prior assets and catalog integration."""

from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.military_score_inference.actions import build_action_catalog_from_turn
from api.analytics.military_score_inference.hull_category import (
    BATTLESHIP_MASS_THRESHOLD,
    resolve_inference_hull_category,
)
from api.analytics.military_score_inference.inference_game_category import (
    BLITZ_INFERENCE_GAME_CATEGORY,
    EPIC_INFERENCE_GAME_CATEGORY,
    STANDARD_INFERENCE_GAME_CATEGORY,
    resolve_inference_game_category,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceProblem
from api.analytics.military_score_inference.prior_weights import (
    PRIOR_WEIGHT_SCALE,
    SMALL_DEEP_SPACE_FREIGHTER_HULL_ID,
    WILDCARD_COUNT_KEY,
    PriorWeightsCatalog,
    PriorWeightsDiagnostics,
    counts_to_log_weights,
    default_prior_weights_dir,
    expand_wildcard_counts,
    implicit_uniform_component_counts,
    load_prior_weights_for_category,
    parse_prior_weights_document,
    resolve_prior_weights_catalog,
    ship_limit_band_key,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.analytics.military_score_inference.solver import STATUS_EXACT, solve_inference_problem
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.models.components import Beam, Engine, Hull, Torpedo

from tests.fixtures.military_score_inference import _observation


def _beam_ship_hull() -> Hull:
    return Hull(
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


def _torpedo_hull() -> Hull:
    return Hull(
        id=65,
        name="Torpedo Frigate",
        tritanium=20,
        duranium=10,
        molybdenum=5,
        fueltank=120,
        crew=40,
        engines=1,
        mass=80,
        techlevel=2,
        cargo=20,
        fighterbays=0,
        launchers=2,
        beams=1,
        cancloak=False,
        cost=50,
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


def _battleship_hull() -> Hull:
    return replace(
        _torpedo_hull(),
        id=90,
        name="Heavy Battleship",
        mass=BATTLESHIP_MASS_THRESHOLD + 50,
        beams=4,
        launchers=4,
    )


def test_resolve_inference_game_category_rules(sample_turn):
    assert resolve_inference_game_category(replace(sample_turn.settings, endturn=30)) == (
        BLITZ_INFERENCE_GAME_CATEGORY
    )
    assert (
        resolve_inference_game_category(replace(sample_turn.settings, endturn=31, shiplimit=499))
        == STANDARD_INFERENCE_GAME_CATEGORY
    )
    assert (
        resolve_inference_game_category(replace(sample_turn.settings, endturn=100, shiplimit=500))
        == EPIC_INFERENCE_GAME_CATEGORY
    )


def test_resolve_inference_hull_category_priority():
    freighter = replace(_beam_ship_hull(), id=15, beams=0, launchers=0, fighterbays=0)
    assert resolve_inference_hull_category(freighter) == "true_freighter"
    assert resolve_inference_hull_category(_beam_ship_hull(), beam_count=0, launcher_count=0) == (
        "weaponless_hull"
    )
    carrier = replace(_beam_ship_hull(), fighterbays=4, beams=0)
    assert resolve_inference_hull_category(carrier) == "carrier"
    assert resolve_inference_hull_category(_torpedo_hull(), beam_count=1, launcher_count=2) == (
        "torpedo_ship"
    )
    assert resolve_inference_hull_category(_battleship_hull(), beam_count=4, launcher_count=4) == (
        "battleship"
    )
    assert resolve_inference_hull_category(_beam_ship_hull(), beam_count=2, launcher_count=0) == (
        "beam_ship"
    )


def test_counts_to_log_weights_prefers_likely_cells():
    likely = counts_to_log_weights({1: 900, 2: 100})
    unlikely = counts_to_log_weights({1: 100, 2: 900})
    assert likely[1] > likely[2]
    assert unlikely[1] < unlikely[2]


def test_standard_prior_asset_loads():
    asset, path, fell_back = load_prior_weights_for_category(STANDARD_INFERENCE_GAME_CATEGORY)
    assert not fell_back
    assert path.name == "prior_weights_standard.yaml"
    assert asset.category == STANDARD_INFERENCE_GAME_CATEGORY
    assert asset.version == 2
    assert asset.hulls["before_ship_limit"]["global"][WILDCARD_COUNT_KEY] == 50


def test_missing_category_falls_back_to_standard(tmp_path: Path):
    standard_src = default_prior_weights_dir() / "prior_weights_standard.yaml"
    tmp_path.joinpath("prior_weights_standard.yaml").write_text(
        standard_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    asset, path, fell_back = load_prior_weights_for_category(
        BLITZ_INFERENCE_GAME_CATEGORY,
        base_dir=tmp_path,
    )
    assert fell_back
    assert path.name == "prior_weights_standard.yaml"
    assert asset.category == STANDARD_INFERENCE_GAME_CATEGORY


def test_wildcard_expands_unlisted_buildable_hull(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({15, 24, 99}),
        eligible_engine_ids=frozenset({1, 5}),
        eligible_beam_ids=frozenset({1, 3}),
        eligible_torp_ids=frozenset({1, 8}),
    )
    assert 99 in catalog.hull_log_weights
    assert catalog.hull_log_weights[24] > catalog.hull_log_weights[99]


def test_expand_wildcard_counts_fills_universe():
    expanded = expand_wildcard_counts(
        {"*": 10, 24: 100},
        universe=frozenset({24, 15}),
    )
    assert expanded == {24: 100, 15: 10}


def _minimal_prior_weights_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "version": 2,
        "category": "standard",
        "gameCategoryRulesVersion": 1,
        "hulls": {
            "before_ship_limit": {"global": {}},
            "after_ship_limit": {"global": {}},
        },
        "components": {
            "before_ship_limit": {},
            "after_ship_limit": {},
        },
        "aggregates": {
            "before_ship_limit": {},
            "after_ship_limit": {},
        },
    }
    document.update(overrides)
    return document


def test_histogram_rejects_wildcard_key():
    with pytest.raises(ValueError, match="must be integers"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": {
                        "planet_defense_posts_added_total": {"histogram": {"*": 10, 5: 1}}
                    },
                    "after_ship_limit": {},
                }
            )
        )


def test_aggregates_reject_unknown_histogram_action_id():
    with pytest.raises(ValueError, match="not a known bucketed aggregate action"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": {
                        "planet_defense_posts_typo": {"histogram": {5: 1}}
                    },
                    "after_ship_limit": {},
                }
            )
        )


def test_aggregates_reject_unknown_counts_action_id():
    with pytest.raises(ValueError, match="not a known counts aggregate action"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": {
                        "evil_empire_free_starbase_fighters": {"counts": {"default": 10}}
                    },
                    "after_ship_limit": {},
                }
            )
        )


def test_aggregates_reject_counts_with_multiple_keys():
    with pytest.raises(ValueError, match="must have exactly one key"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": {
                        "fighters_starbase_to_ship": {
                            "counts": {"default": 65, "alternate": 10}
                        }
                    },
                    "after_ship_limit": {},
                }
            )
        )


def test_aggregates_reject_empty_counts():
    with pytest.raises(ValueError, match="must have exactly one key"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": {
                        "fighters_ship_to_starbase": {"counts": {}}
                    },
                    "after_ship_limit": {},
                }
            )
        )


def test_component_tables_reject_unknown_hull_category():
    with pytest.raises(ValueError, match="not a valid inference hull category"):
        parse_prior_weights_document(
            {
                "version": 2,
                "category": "standard",
                "gameCategoryRulesVersion": 1,
                "hulls": {
                    "before_ship_limit": {"global": {}},
                    "after_ship_limit": {"global": {}},
                },
                "components": {
                    "before_ship_limit": {"beam_ships": {"engines": {1: 1}}},
                    "after_ship_limit": {},
                },
                "aggregates": {
                    "before_ship_limit": {},
                    "after_ship_limit": {},
                },
            }
        )


def test_slotfill_rejects_wildcard_key():
    with pytest.raises(ValueError, match="does not allow '\\*'"):
        parse_prior_weights_document(
            {
                "version": 2,
                "category": "standard",
                "gameCategoryRulesVersion": 1,
                "hulls": {
                    "before_ship_limit": {"global": {}},
                    "after_ship_limit": {"global": {}},
                },
                "components": {
                    "before_ship_limit": {"beam_ship": {"slotFill": {"*": 10, "full": 1}}},
                    "after_ship_limit": {},
                },
                "aggregates": {
                    "before_ship_limit": {},
                    "after_ship_limit": {},
                },
            }
        )


def test_implicit_uniform_component_counts_are_equal_per_id():
    counts = implicit_uniform_component_counts(frozenset({2, 3, 5}))
    assert counts == {2: 1.0, 3: 1.0, 5: 1.0}


def test_missing_component_subtable_uses_uniform_distribution(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({65}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({2, 3}),
        eligible_torp_ids=frozenset({1, 8}),
    )
    hull = _torpedo_hull()
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

    beams_table = catalog.component_tables["torpedo_ship"]["beams"]
    expected_uniform_weight = counts_to_log_weights({2: 1.0, 3: 1.0}, scale=PRIOR_WEIGHT_SCALE)[2]

    assert with_beam_two == with_beam_three
    assert beams_table[2] == beams_table[3] == expected_uniform_weight
    assert expected_uniform_weight < 0


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
    hull = _beam_ship_hull()
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


def _minimal_prior_catalog(
    *,
    hull_log_weights: dict[int, int] | None = None,
    combo_log_overrides: dict[str, int] | None = None,
    hull_log_overrides: dict[int, int] | None = None,
) -> PriorWeightsCatalog:
    return PriorWeightsCatalog(
        diagnostics=PriorWeightsDiagnostics(
            category_id="standard",
            asset_path="test",
            asset_version=1,
            game_category_rules_version=1,
            fell_back_to_standard=False,
            ship_limit_band="before_ship_limit",
            race_id_used=None,
        ),
        hull_log_weights=hull_log_weights or {},
        component_tables={},
        aggregate_action_weights={},
        aggregate_bucket_marginal_weights={},
        combo_log_overrides=combo_log_overrides or {},
        hull_log_overrides=hull_log_overrides or {},
    )


def test_freighter_probability_weight_uses_sdsf_hull_marginal():
    catalog = _minimal_prior_catalog(
        hull_log_weights={SMALL_DEEP_SPACE_FREIGHTER_HULL_ID: 42},
    )
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            default_weight=80,
        )
        == 42
    )


def test_freighter_probability_weight_prefers_combo_then_hull_override():
    catalog = _minimal_prior_catalog(
        hull_log_weights={SMALL_DEEP_SPACE_FREIGHTER_HULL_ID: 42},
        hull_log_overrides={SMALL_DEEP_SPACE_FREIGHTER_HULL_ID: 55},
        combo_log_overrides={GENERIC_FREIGHTER_COMBO_ID: 99},
    )
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            default_weight=80,
        )
        == 99
    )
    without_combo = _minimal_prior_catalog(
        hull_log_weights={SMALL_DEEP_SPACE_FREIGHTER_HULL_ID: 42},
        hull_log_overrides={SMALL_DEEP_SPACE_FREIGHTER_HULL_ID: 55},
    )
    assert (
        without_combo.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            default_weight=80,
        )
        == 55
    )


def test_freighter_probability_weight_falls_back_to_default():
    catalog = _minimal_prior_catalog()
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            default_weight=80,
        )
        == 80
    )


def test_catalog_build_includes_prior_weights_diagnostics(sample_turn):
    observation = _observation()
    full_step = resolve_tier_policies()[-1]
    catalog = build_action_catalog_from_turn(observation, sample_turn, policy_step=full_step)

    assert catalog.prior_weights is not None
    diagnostics = catalog.diagnostics()
    assert "priorWeights" in diagnostics
    prior_payload = diagnostics["priorWeights"]
    assert isinstance(prior_payload, dict)
    assert prior_payload["categoryId"] == resolve_inference_game_category(sample_turn.settings)
    assert prior_payload["shipLimitBand"] == ship_limit_band_key(observation)


def test_top_k_prefers_higher_prior_feasible_combo(sample_turn, synthetic_catalog_context):
    from api.analytics.military_score_inference.models import ShipBuildCombo
    from api.analytics.military_score_inference.ship_build_combos import ship_build_combo_id

    hull = synthetic_catalog_context["hulls_by_id"][24]
    engine = synthetic_catalog_context["engines_by_id"][1]
    beam = synthetic_catalog_context["beams_by_id"][1]
    prior_catalog = resolve_prior_weights_catalog(
        _observation(military_delta_2x=400, warship_delta=1),
        sample_turn.settings,
        race_id=sample_turn.player.raceid,
        buildable_hull_ids=synthetic_catalog_context["buildable_hull_ids"],
        eligible_engine_ids=synthetic_catalog_context["eligible_engine_ids"],
        eligible_beam_ids=synthetic_catalog_context["eligible_beam_ids"],
        eligible_torp_ids=synthetic_catalog_context["eligible_torp_ids"],
    )
    likely_weight = prior_catalog.combo_probability_weight(
        combo_id="likely",
        hull=hull,
        engine=engine,
        beam=beam,
        torpedo=None,
        beam_count=hull.beams,
        launcher_count=0,
    )
    unlikely_weight = prior_catalog.combo_probability_weight(
        combo_id="unlikely",
        hull=hull,
        engine=engine,
        beam=beam,
        torpedo=None,
        beam_count=1,
        launcher_count=0,
    )
    assert likely_weight > unlikely_weight

    likely_combo = ShipBuildCombo(
        combo_id=ship_build_combo_id(
            hull_id=hull.id,
            engine_id=engine.id,
            beam_id=beam.id,
            torp_id=None,
            beam_count=hull.beams,
            launcher_count=0,
        ),
        hull_id=hull.id,
        engine_id=engine.id,
        beam_id=beam.id,
        torp_id=None,
        beam_count=hull.beams,
        launcher_count=0,
        hull_beam_slots=hull.beams,
        hull_launcher_slots=hull.launchers,
        labels=("Likely build",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=likely_weight,
    )
    unlikely_combo = ShipBuildCombo(
        combo_id=ship_build_combo_id(
            hull_id=hull.id,
            engine_id=engine.id,
            beam_id=beam.id,
            torp_id=None,
            beam_count=1,
            launcher_count=0,
        ),
        hull_id=hull.id,
        engine_id=engine.id,
        beam_id=beam.id,
        torp_id=None,
        beam_count=1,
        launcher_count=0,
        hull_beam_slots=hull.beams,
        hull_launcher_slots=hull.launchers,
        labels=("Unlikely build",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=unlikely_weight,
    )
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=400,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(),
            ship_build_combos=(likely_combo, unlikely_combo),
            max_solutions=2,
        )
    )

    assert result.status == STATUS_EXACT
    assert len(result.solutions) == 2
    assert result.solutions[0].ship_builds[0].combo_id == likely_combo.combo_id
    assert result.solutions[0].objective_value >= result.solutions[1].objective_value
