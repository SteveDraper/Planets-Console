"""Tests for fleet-informed torpedo admission and ranking overlay (#87)."""

from __future__ import annotations

from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_action_catalog,
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.fleet_torp_overlay import (
    FleetLauncherBeliefSet,
    FleetTorpOverlay,
    admitted_torp_ids_for_policy_step,
    apply_torp_misalignment_penalty_to_buckets,
    launcher_belief_set_from_composition,
    launcher_belief_set_from_fleet_records,
    torp_load_action_id,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.ship_build_combos import ship_build_combo_id
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.solver import STATUS_EXACT, solve_inference_problem
from api.analytics.military_score_inference.tier_policy import (
    TORP_ESCAPE_TIER_STEP_ID,
    InferenceTierPolicyStep,
    resolve_fleet_inference_tuning,
    resolve_tier_policies,
)

from tests.fixtures.military_score_inference import _observation
from tests.fixtures.military_score_inference_prior_weights import (
    minimal_prior_catalog,
    probability_buckets_for_test_action,
)


def _legacy_overlay() -> FleetTorpOverlay:
    return FleetTorpOverlay.disabled()


def _torp_step():
    return next(step for step in resolve_tier_policies() if step.id == "admit_ship_torpedoes")


def _escape_step():
    return next(step for step in resolve_tier_policies() if step.id == TORP_ESCAPE_TIER_STEP_ID)


def _torp_action_ids(catalog: ActionCatalog) -> set[str]:
    return {
        action.id
        for action in catalog.aggregate_actions
        if action.id.startswith("ship_torps_loaded_")
    }


def _torp_and_escape_step_indices() -> tuple[
    tuple[InferenceTierPolicyStep, ...], int, int
]:
    policy_steps = resolve_tier_policies()
    torp_step_index = next(
        index for index, step in enumerate(policy_steps) if step.id == "admit_ship_torpedoes"
    )
    escape_step_index = next(
        index for index, step in enumerate(policy_steps) if step.id == TORP_ESCAPE_TIER_STEP_ID
    )
    return policy_steps, torp_step_index, escape_step_index


def test_belief_set_from_composition_histogram():
    belief = launcher_belief_set_from_composition({"launcherTypes": {"4": 2, "8": 1}})
    assert belief.torp_ids == frozenset({4, 8})


def test_belief_set_from_fleet_records_unions_option_sets():
    record = FleetShipRecord(
        record_id="inferred",
        disposition="active",
        fields=FleetShipRecordFields(
            launchers=FleetFieldKnown(4),
        ),
        build_option_sets=[
            FleetBuildOptionSet(torp_id=4, label="Mk IV default"),
            FleetBuildOptionSet(torp_id=8, label="Mk VIII alt"),
        ],
    )
    belief = launcher_belief_set_from_fleet_records([record])
    assert belief.torp_ids == frozenset({4, 8})


def test_absent_overlay_is_empty_belief_set_on_early_torp_tier(sample_turn):
    torp_step = _torp_step()
    catalog = build_action_catalog_from_turn(
        _observation(military_delta_2x=500),
        sample_turn,
        policy_step=torp_step,
    )
    torp_action_ids = {
        action.id
        for action in catalog.aggregate_actions
        if action.id.startswith("ship_torps_loaded_")
    }
    assert not torp_action_ids
    assert catalog.fleet_torp_overlay_diagnostics is not None
    assert catalog.fleet_torp_overlay_diagnostics.enabled is True
    assert catalog.fleet_torp_overlay_diagnostics.belief_set_torp_ids == ()


def _catalog_context(synthetic_catalog_context):
    return {
        key: value for key, value in synthetic_catalog_context.items() if key != "prior_catalog"
    }


def test_belief_set_admits_only_matching_torps_on_early_tier(
    synthetic_catalog_context,
):
    torp_step = _torp_step()
    belief_torp_id = next(iter(synthetic_catalog_context["eligible_torp_ids"]))
    overlay = FleetTorpOverlay.from_torp_ids(frozenset({belief_torp_id}))
    catalog = build_action_catalog(
        _observation(military_delta_2x=500),
        policy_step=torp_step,
        prior_catalog=minimal_prior_catalog(),
        fleet_torp_overlay=overlay,
        **_catalog_context(synthetic_catalog_context),
    )
    torp_action_ids = {
        action.id
        for action in catalog.aggregate_actions
        if action.id.startswith("ship_torps_loaded_")
    }
    assert torp_action_ids == {torp_load_action_id(belief_torp_id)}


def test_escape_tier_admits_all_eligible_torps(synthetic_catalog_context):
    escape_step = _escape_step()
    belief_torp_id = next(iter(synthetic_catalog_context["eligible_torp_ids"]))
    overlay = FleetTorpOverlay.from_torp_ids(frozenset({belief_torp_id}))
    catalog = build_action_catalog(
        _observation(military_delta_2x=500),
        policy_step=escape_step,
        prior_catalog=minimal_prior_catalog(),
        fleet_torp_overlay=overlay,
        **_catalog_context(synthetic_catalog_context),
    )
    torp_action_ids = {
        action.id
        for action in catalog.aggregate_actions
        if action.id.startswith("ship_torps_loaded_")
    }
    assert len(torp_action_ids) == len(synthetic_catalog_context["eligible_torp_ids"])
    assert catalog.fleet_torp_overlay_diagnostics is not None
    assert catalog.fleet_torp_overlay_diagnostics.escape_tier_used is True


def test_disabled_overlay_matches_legacy_torp_admission(sample_turn):
    torp_step = _torp_step()
    catalog = build_action_catalog_from_turn(
        _observation(military_delta_2x=500),
        sample_turn,
        policy_step=torp_step,
        fleet_torp_overlay=_legacy_overlay(),
    )
    torp_actions = [
        action for action in catalog.aggregate_actions if action.id.startswith("ship_torps_loaded_")
    ]
    assert torp_actions
    assert catalog.fleet_torp_overlay_diagnostics is not None
    assert catalog.fleet_torp_overlay_diagnostics.enabled is False


def test_misalignment_penalty_reduces_active_bin_weights():
    buckets = probability_buckets_for_test_action("ship_torps_loaded_1")
    penalized = apply_torp_misalignment_penalty_to_buckets(buckets, penalty=50)
    assert penalized[0].marginal_weight == buckets[0].marginal_weight
    assert penalized[1].marginal_weight == buckets[1].marginal_weight - 50


def test_non_belief_torp_gets_penalty_on_escape_tier(synthetic_catalog_context):
    from api.models.components import Torpedo

    second_torp = Torpedo(
        id=2,
        fullid=2,
        name="Mark 2 Photon",
        torpedocost=2,
        launchercost=2,
        tritanium=1,
        duranium=1,
        molybdenum=0,
        mass=1,
        techlevel=2,
        crewkill=10,
        damage=5,
        combatrange=0,
    )
    context = _catalog_context(synthetic_catalog_context)
    context["torpedos_by_id"] = {
        **context["torpedos_by_id"],
        second_torp.id: second_torp,
    }
    context["eligible_torp_ids"] = frozenset({1, 2})
    escape_step = _escape_step()
    overlay = FleetTorpOverlay.from_torp_ids(frozenset({1}))
    catalog = build_action_catalog(
        _observation(military_delta_2x=500),
        policy_step=escape_step,
        prior_catalog=minimal_prior_catalog(),
        fleet_torp_overlay=overlay,
        **context,
    )
    belief_buckets = catalog.probability_buckets_by_action_id[torp_load_action_id(1)]
    non_belief_buckets = catalog.probability_buckets_by_action_id[torp_load_action_id(2)]
    penalty = resolve_fleet_inference_tuning().torp_misalignment_log_penalty
    assert non_belief_buckets[1].marginal_weight == belief_buckets[1].marginal_weight - penalty


def test_ranking_ship_build_beats_belief_torp_beats_non_belief_torp():
    ship_combo = ShipBuildCombo(
        combo_id=ship_build_combo_id(
            hull_id=15,
            engine_id=1,
            beam_id=None,
            torp_id=None,
            beam_count=0,
            launcher_count=0,
        ),
        hull_id=15,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        hull_beam_slots=0,
        hull_launcher_slots=0,
        labels=("Freighter build",),
        score_delta_2x=400,
        freighter_delta=0,
        upper_bound=1,
        probability_weight=200,
    )
    belief_torp = CandidateAction(
        id=torp_load_action_id(1),
        label="Belief torp",
        score_delta_2x=400,
        upper_bound=1,
    )
    non_belief_torp = CandidateAction(
        id=torp_load_action_id(2),
        label="Non-belief torp",
        score_delta_2x=400,
        upper_bound=1,
    )
    belief_buckets = probability_buckets_for_test_action(torp_load_action_id(1))
    torp_one_weights = tuple(bucket.marginal_weight for bucket in belief_buckets)
    non_belief_buckets = apply_torp_misalignment_penalty_to_buckets(
        probability_buckets_for_test_action(
            torp_load_action_id(2),
            marginal_weights=torp_one_weights,
        ),
        penalty=50,
    )
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=400,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
    )
    narrowed = ActionCatalog(
        aggregate_actions=(belief_torp, non_belief_torp),
        ship_build_combos=(ship_combo,),
        probability_buckets_by_action_id={
            belief_torp.id: belief_buckets,
            non_belief_torp.id: non_belief_buckets,
        },
    )
    result = solve_inference_problem(
        build_inference_problem(observation, narrowed, max_solutions=3)
    )
    assert result.status == STATUS_EXACT
    assert len(result.solutions) == 3
    top = result.solutions[0]
    second = result.solutions[1]
    third = result.solutions[2]
    assert top.ship_builds and top.ship_builds[0].combo_id == ship_combo.combo_id
    assert second.actions and second.actions[0].action_id == belief_torp.id
    assert third.actions and third.actions[0].action_id == non_belief_torp.id
    assert top.objective_value >= second.objective_value >= third.objective_value


def test_solve_with_policy_ladder_fleet_torp_overlay_belief_set(sample_turn):
    """Full ladder walk: empty belief defers torps until escape; belief admits early."""
    observation = _observation(military_delta_2x=500)
    policy_steps, torp_step_index, escape_step_index = _torp_and_escape_step_indices()
    torp_step = policy_steps[torp_step_index]
    escape_step = policy_steps[escape_step_index]

    empty_overlay = FleetTorpOverlay(
        belief_set=FleetLauncherBeliefSet(frozenset()),
        enabled=True,
    )
    _, final_catalog, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        fleet_torp_overlay=empty_overlay,
        time_limit_seconds=60.0,
    )

    assert "admit_ship_torpedoes" in attempted
    assert TORP_ESCAPE_TIER_STEP_ID in attempted

    early_catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=torp_step,
        policy_step_index=torp_step_index,
        fleet_torp_overlay=empty_overlay,
    )
    assert not _torp_action_ids(early_catalog)
    assert early_catalog.fleet_torp_overlay_diagnostics is not None
    assert early_catalog.fleet_torp_overlay_diagnostics.belief_set_torp_ids == ()

    escape_catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=escape_step,
        policy_step_index=escape_step_index,
        fleet_torp_overlay=empty_overlay,
    )
    assert _torp_action_ids(escape_catalog)
    assert escape_catalog.fleet_torp_overlay_diagnostics is not None
    assert escape_catalog.fleet_torp_overlay_diagnostics.escape_tier_used is True

    assert final_catalog is not None
    assert _torp_action_ids(final_catalog)

    belief_torp_id = 1
    belief_overlay = FleetTorpOverlay.from_torp_ids(frozenset({belief_torp_id}))
    _, _, _, belief_attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        fleet_torp_overlay=belief_overlay,
        time_limit_seconds=60.0,
    )
    assert "admit_ship_torpedoes" in belief_attempted

    belief_early_catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=torp_step,
        policy_step_index=torp_step_index,
        fleet_torp_overlay=belief_overlay,
    )
    assert _torp_action_ids(belief_early_catalog) == {torp_load_action_id(belief_torp_id)}
    assert belief_early_catalog.fleet_torp_overlay_diagnostics is not None
    assert belief_early_catalog.fleet_torp_overlay_diagnostics.admitted_torp_ids == (
        belief_torp_id,
    )


def test_admitted_torp_ids_respects_option_set_union():
    belief = FleetLauncherBeliefSet(frozenset({4, 8}))
    overlay = FleetTorpOverlay(belief_set=belief)
    policy_steps = resolve_tier_policies()
    torp_step = _torp_step()
    torp_step_index = next(
        index for index, step in enumerate(policy_steps) if step.id == torp_step.id
    )
    admitted = admitted_torp_ids_for_policy_step(
        policy_step=torp_step,
        policy_step_index=torp_step_index,
        policy_steps=policy_steps,
        eligible_torp_ids=frozenset({1, 2, 3, 4, 8}),
        overlay=overlay,
    )
    assert admitted == frozenset({4, 8})
