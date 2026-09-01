"""Catalog-to-solver regressions for ship transfer families (#370)."""

from dataclasses import replace

from api.analytics.military_score_inference.actions import (
    build_action_catalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.score_arithmetic import (
    solution_military_score_arithmetic_payload,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    ACQUIRED_SHIP_ACTION_PREFIX,
    GIFT_ACTION_PREFIX,
    SHIP_LOSS_ACTION_PREFIX,
    TRADE_ACTION_PREFIX,
    ShipTransferCatalogFragment,
    build_ship_transfer_catalog_fragment,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    solve_inference_problem,
)

from tests.fixtures.military_score_inference import _observation
from tests.fixtures.pp_gap_transfer import (
    BIRDS_PLAYER_ID,
    FEDERATION_PLAYER_ID,
    mixed_residual_receiver_observation,
    privateer_observation,
    privateer_peer_rows,
)
from tests.fixtures.ship_transfer_families import (
    _class_flip_trade_catalog,
    _known_warship_record,
    _peer_row,
    _same_class_swap_catalog,
    _transfer_catalog_kwargs,
    _two_ship_class_flip_trade_fragment,
)


def test_flat_observation_empty_solution_ranks_strictly_above_phantom_loss_replace(
    synthetic_catalog_build_context,
):
    record, _military_2x = _known_warship_record(synthetic_catalog_build_context)
    observation = _observation(military_delta_2x=0, warship_delta=0)
    catalog = build_action_catalog(
        observation,
        **synthetic_catalog_build_context,
        prior_fleet_records=(record,),
    )
    assert any(
        action.id.startswith(SHIP_LOSS_ACTION_PREFIX) for action in catalog.aggregate_actions
    )
    result = solve_inference_problem(
        build_inference_problem(observation, catalog, time_limit_seconds=5.0)
    )
    assert result.status == STATUS_EXACT
    best = result.solutions[0]
    assert best.actions == ()
    assert best.ship_builds == ()
    for solution in result.solutions[1:]:
        assert solution.objective_value < best.objective_value


def test_catalog_solver_genuine_loss_stays_exact_with_transfer_penalty(
    synthetic_catalog_build_context,
):
    record, military_2x = _known_warship_record(synthetic_catalog_build_context)
    observation = replace(
        _observation(military_delta_2x=-military_2x, warship_delta=-1),
        priority_point_delta=1,
    )
    catalog = build_action_catalog(
        observation,
        **synthetic_catalog_build_context,
        prior_fleet_records=(record,),
    )
    result = solve_inference_problem(
        build_inference_problem(observation, catalog, time_limit_seconds=5.0)
    )
    assert result.status == STATUS_EXACT
    best_action_ids = {action.action_id for action in result.solutions[0].actions}
    assert f"{SHIP_LOSS_ACTION_PREFIX}warship:point:{military_2x}" in best_action_ids


def test_catalog_solver_class_flip_trade_when_matching_hull_is_not_first_group(
    synthetic_catalog_context,
):
    observation, fragment, _first_military, matching_military = _class_flip_trade_catalog(
        synthetic_catalog_context
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            prior_warship_departure_cap=2,
            prior_departure_group_caps=fragment.prior_departure_group_caps,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    chosen = result.solutions[0].actions[0]
    assert chosen.action_id == f"{TRADE_ACTION_PREFIX}warship:with:3:point:{matching_military}"
    assert chosen.counterparty_player_id == 3


def test_catalog_solver_same_class_swap_is_exact(synthetic_catalog_context):
    observation, fragment = _same_class_swap_catalog(synthetic_catalog_context)
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            prior_warship_departure_cap=fragment.prior_warship_departure_cap,
            prior_departure_group_caps=fragment.prior_departure_group_caps,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    chosen = result.solutions[0].actions[0]
    assert (
        chosen.action_id
        == f"{TRADE_ACTION_PREFIX}warship:with:3:swap:{observation.military_delta_2x}"
    )
    assert chosen.counterparty_player_id == 3


def _partial_gift_two_departure_fragment(
    synthetic_catalog_context,
    *,
    second_record_beam_count: int,
) -> tuple[InferenceObservation, ShipTransferCatalogFragment, int, int]:
    """Fragment where a partial gift admits loss and gift actions over shared groups.

    The observation drops two warships while claiming twice the first record's
    military; the peer row absorbs only one warship, so the other drop stays
    unmatched and the loss family is admitted alongside the gift family.
    """
    first, first_military = _known_warship_record(
        synthetic_catalog_context,
        beam_count=2,
        record_id="departure-first",
    )
    second, second_military = _known_warship_record(
        synthetic_catalog_context,
        beam_count=second_record_beam_count,
        record_id="departure-second",
    )
    observation = replace(
        _observation(military_delta_2x=-2 * first_military, warship_delta=-2),
        priority_point_delta=1,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=1, military_2x=first_military),),
        prior_fleet_records=(first, second),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    return observation, fragment, first_military, second_military


def _solve_partial_gift_two_departure(
    observation: InferenceObservation,
    fragment: ShipTransferCatalogFragment,
):
    return solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            prior_warship_departure_cap=fragment.prior_warship_departure_cap,
            prior_departure_group_caps=fragment.prior_departure_group_caps,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )


def test_group_departure_capacity_forbids_single_record_double_claim(
    synthetic_catalog_context,
):
    observation, fragment, first_military, second_military = _partial_gift_two_departure_fragment(
        synthetic_catalog_context,
        second_record_beam_count=1,
    )
    assert second_military != first_military
    result = _solve_partial_gift_two_departure(observation, fragment)
    assert result.status != STATUS_EXACT
    assert result.solutions == ()


def test_group_departure_capacity_allows_two_records_in_same_group(
    synthetic_catalog_context,
):
    observation, fragment, first_military, second_military = _partial_gift_two_departure_fragment(
        synthetic_catalog_context,
        second_record_beam_count=2,
    )
    assert second_military == first_military
    result = _solve_partial_gift_two_departure(observation, fragment)
    assert result.status == STATUS_EXACT
    for solution in result.solutions:
        action_ids = {action.action_id for action in solution.actions}
        assert action_ids == {
            f"{SHIP_LOSS_ACTION_PREFIX}warship:point:{first_military}",
            f"{GIFT_ACTION_PREFIX}warship:to:3:point:{first_military}",
        }
        assert sum(action.count for action in solution.actions) == 2


def test_catalog_solver_two_ship_acquired_is_exact(synthetic_catalog_context):
    observation = replace(
        _observation(military_delta_2x=40, warship_delta=2),
        priority_point_delta=1,
    )
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(_peer_row(3, warship=-2, military_2x=-40),),
        prior_fleet_records=(),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    acquired = next(
        action for action in fragment.actions if action.id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
    )
    assert acquired.upper_bound == 2
    assert acquired.score_delta_2x_min == 0
    assert acquired.score_delta_2x_max == 40
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            prior_departure_group_caps=fragment.prior_departure_group_caps,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    chosen = result.solutions[0].actions[0]
    assert chosen.action_id == f"{ACQUIRED_SHIP_ACTION_PREFIX}warship:from:3"
    assert chosen.count == 2


def test_catalog_solver_two_ship_class_flip_trade_is_exact(synthetic_catalog_context):
    first, military_2x = _known_warship_record(synthetic_catalog_context, record_id="serpent-a")
    second, _ = _known_warship_record(synthetic_catalog_context, record_id="serpent-b")
    observation, fragment = _two_ship_class_flip_trade_fragment(
        synthetic_catalog_context,
        (first, second),
        military_delta_2x=-2 * military_2x,
    )
    trade = next(action for action in fragment.actions if action.id.startswith(TRADE_ACTION_PREFIX))
    assert trade.score_delta_2x == -2 * military_2x
    assert trade.prior_warship_usage == 2
    assert trade.upper_bound == 1
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            prior_warship_departure_cap=fragment.prior_warship_departure_cap,
            prior_departure_group_caps=fragment.prior_departure_group_caps,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    chosen = result.solutions[0].actions[0]
    assert chosen.action_id == f"{TRADE_ACTION_PREFIX}warship:with:3:point:{military_2x}"
    assert chosen.count == 1


def _privateer_build_combo() -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id="combo_meteor",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=None,
        beam_count=2,
        launcher_count=0,
        labels=("Meteor",),
        score_delta_2x=40,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=2,
    )


def test_pp_gap_solver_privateer_pairs_one_donor_fed_or_birds(
    sample_turn, synthetic_catalog_context
):
    observation = privateer_observation()
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=privateer_peer_rows(),
        prior_fleet_records=(),
        settings=sample_turn.settings,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    combo = _privateer_build_combo()
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            ship_build_combos=(combo,),
            enforce_idle_dock_pp_equality=True,
            acquired_warship_cap=fragment.reserved_incoming_warships,
            acquired_ship_cap=fragment.reserved_incoming_ships,
            max_solutions=5,
            time_limit_seconds=5.0,
        )
    )
    assert result.status == STATUS_EXACT
    leftover_2x = observation.military_delta_2x - 2 * combo.score_delta_2x
    actions_by_id = {action.id: action for action in fragment.actions}
    counterparties_by_solution = []
    for solution in result.solutions:
        acquired = [
            action
            for action in solution.actions
            if action.action_id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
        ]
        assert len(acquired) == 1
        assert acquired[0].count == 1
        counterparties_by_solution.append(acquired[0].counterparty_player_id)
        assert solution.ship_builds[0].count == 2
        arithmetic = solution_military_score_arithmetic_payload(
            solution,
            observation,
            actions_by_id,
            {combo.combo_id: combo},
        )
        acquired_line = next(
            item
            for item in arithmetic["lineItems"]
            if str(item.get("actionId", "")).startswith(ACQUIRED_SHIP_ACTION_PREFIX)
        )
        catalog_acquired = actions_by_id[acquired[0].action_id]
        assert catalog_acquired.score_delta_2x_max == observation.military_delta_2x
        assert acquired_line["scoreDelta2xSubtotal"] == leftover_2x
        assert leftover_2x < observation.military_delta_2x
        assert arithmetic["matchesObserved"] is True
    assert set(counterparties_by_solution) == {FEDERATION_PLAYER_ID, BIRDS_PLAYER_ID}


def test_pp_gap_solver_does_not_consume_every_excess_out_donor(
    sample_turn, synthetic_catalog_context
):
    """Without idle-dock, 1 build + 2 acquired would hit +3 warships -- that is forbidden."""
    observation = privateer_observation()
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=privateer_peer_rows(),
        prior_fleet_records=(),
        settings=sample_turn.settings,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    wide_combo = ShipBuildCombo(
        combo_id="combo_meteor",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=None,
        beam_count=2,
        launcher_count=0,
        labels=("Meteor",),
        score_delta_2x=40,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=3,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            ship_build_combos=(wide_combo,),
            acquired_warship_cap=fragment.reserved_incoming_warships,
            acquired_ship_cap=fragment.reserved_incoming_ships,
            max_solutions=5,
            time_limit_seconds=5.0,
        )
    )
    assert result.status == STATUS_EXACT
    for solution in result.solutions:
        acquired = [
            action
            for action in solution.actions
            if action.action_id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
        ]
        assert sum(action.count for action in acquired) == 1


def test_pp_gap_solver_unpaired_acquired_stays_no_exact_solution(
    sample_turn, synthetic_catalog_context
):
    observation = privateer_observation()
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(),
        prior_fleet_records=(),
        settings=sample_turn.settings,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert not any(action.id.startswith(ACQUIRED_SHIP_ACTION_PREFIX) for action in fragment.actions)
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            ship_build_combos=(_privateer_build_combo(),),
            enforce_idle_dock_pp_equality=True,
            max_solutions=5,
            time_limit_seconds=5.0,
        )
    )
    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert result.solutions == ()


def _mixed_residual_build_combos() -> tuple[ShipBuildCombo, ShipBuildCombo]:
    return (
        ShipBuildCombo(
            combo_id="combo_warship",
            hull_id=24,
            engine_id=1,
            beam_id=1,
            torp_id=None,
            beam_count=2,
            launcher_count=0,
            labels=("Meteor",),
            score_delta_2x=80,
            warship_delta=1,
            build_slot_usage=1,
            upper_bound=1,
        ),
        ShipBuildCombo(
            combo_id="combo_freighter",
            hull_id=16,
            engine_id=1,
            beam_id=None,
            torp_id=None,
            beam_count=0,
            launcher_count=0,
            labels=("Large Deep Space Freighter",),
            score_delta_2x=0,
            freighter_delta=1,
            build_slot_usage=1,
            upper_bound=1,
        ),
    )


def test_pp_gap_unknown_class_cannot_take_two_acquired_ships(
    sample_turn, synthetic_catalog_context
):
    observation = mixed_residual_receiver_observation()
    fragment = build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=privateer_peer_rows(),
        prior_fleet_records=(),
        settings=sample_turn.settings,
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=fragment.actions,
            ship_build_combos=_mixed_residual_build_combos(),
            acquired_ship_cap=fragment.reserved_incoming_ships,
            max_solutions=20,
            time_limit_seconds=5.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert fragment.reserved_incoming_ships == 1
    for solution in result.solutions:
        acquired = [
            action
            for action in solution.actions
            if action.action_id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
        ]
        assert sum(action.count for action in acquired) <= 1
