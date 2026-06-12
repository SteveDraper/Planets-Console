"""Integration tests for prior weights in catalog build and solver ranking."""

from dataclasses import replace
from itertools import combinations

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.inference_game_category import (
    resolve_inference_game_category,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.prior_weights_resolve import (
    resolve_prior_weights_catalog,
    ship_limit_band_key,
)
from api.analytics.military_score_inference.ship_build_combos import ship_build_combo_id
from api.analytics.military_score_inference.solver import STATUS_EXACT, solve_inference_problem
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies

from tests.fixtures.military_score_inference import _observation

# Player 8 in turn_sample.json only has freighter hull 15 buildable; player 3 has warships.
_SAMPLE_TURN_WARSHIP_PLAYER_ID = 3


def _find_warship_combo_pair_with_prior_gap(
    catalog: ActionCatalog,
) -> tuple[ShipBuildCombo, ShipBuildCombo, int]:
    """Return same-hull warship combos from the catalog that differ in YAML prior weight."""
    warship_combos = [combo for combo in catalog.ship_build_combos if combo.warship_delta == 1]
    by_hull_and_score: dict[tuple[int, int], list[ShipBuildCombo]] = {}
    for combo in warship_combos:
        by_hull_and_score.setdefault((combo.hull_id, combo.score_delta_2x), []).append(combo)

    for group in by_hull_and_score.values():
        for higher_prior, lower_prior in combinations(group, 2):
            if higher_prior.probability_weight == lower_prior.probability_weight:
                continue
            if higher_prior.probability_weight < lower_prior.probability_weight:
                higher_prior, lower_prior = lower_prior, higher_prior
            return higher_prior, lower_prior, higher_prior.score_delta_2x

    raise AssertionError("expected at least one same-hull warship pair with distinct prior weights")


def test_catalog_build_includes_prior_weights_diagnostics(sample_turn):
    observation = _observation()
    full_step = resolve_tier_policies()[-1]
    catalog = build_action_catalog_from_turn(observation, sample_turn, policy_step=full_step)

    assert catalog.prior_weights_diagnostics is not None
    diagnostics = catalog.diagnostics()
    assert "priorWeights" in diagnostics
    prior_payload = diagnostics["priorWeights"]
    assert isinstance(prior_payload, dict)
    assert prior_payload["categoryId"] == resolve_inference_game_category(sample_turn.settings)
    assert prior_payload["shipLimitBand"] == ship_limit_band_key(observation)


def test_top_k_prefers_higher_prior_feasible_combo(sample_turn, synthetic_catalog_context):
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


def test_full_path_catalog_build_top_k_prefers_higher_prior_combo(sample_turn):
    """End-to-end: turn catalog build with standard YAML priors, then solver top-K ranking."""
    bootstrap_observation = InferenceObservation(
        player_id=_SAMPLE_TURN_WARSHIP_PLAYER_ID,
        turn=111,
        military_delta_2x=0,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=3,
        is_after_ship_limit=False,
    )
    full_step = resolve_tier_policies()[-1]
    catalog = build_action_catalog_from_turn(
        bootstrap_observation,
        sample_turn,
        policy_step=full_step,
    )

    assert catalog.prior_weights_diagnostics is not None
    assert catalog.prior_weights_diagnostics.asset_path.endswith("prior_weights_standard.yaml")

    higher_prior, lower_prior, military_score = _find_warship_combo_pair_with_prior_gap(catalog)
    assert higher_prior.probability_weight > lower_prior.probability_weight

    observation = InferenceObservation(
        player_id=_SAMPLE_TURN_WARSHIP_PLAYER_ID,
        turn=111,
        military_delta_2x=military_score,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=3,
        is_after_ship_limit=False,
    )
    narrowed_catalog = replace(
        catalog,
        aggregate_actions=(),
        ship_build_combos=(higher_prior, lower_prior),
    )
    result = solve_inference_problem(
        build_inference_problem(observation, narrowed_catalog, max_solutions=2)
    )

    assert result.status == STATUS_EXACT
    assert len(result.solutions) == 2
    assert result.solutions[0].ship_builds[0].combo_id == higher_prior.combo_id
    assert result.solutions[0].objective_value >= result.solutions[1].objective_value
