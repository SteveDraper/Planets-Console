"""Solver contract for ship loss, gift, trade, and acquired actions (#370)."""

from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    ACQUIRED_SHIP_ACTION_PREFIX,
    GIFT_ACTION_PREFIX,
    SHIP_LOSS_ACTION_PREFIX,
    TRADE_ACTION_PREFIX,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    solve_inference_problem,
)


def test_solver_exact_ship_loss_uses_prior_fleet_military():
    loss = CandidateAction(
        id=f"{SHIP_LOSS_ACTION_PREFIX}warship:point:40",
        label="Ship loss (warship)",
        score_delta_2x=-40,
        warship_delta=-1,
        prior_warship_usage=1,
        upper_bound=1,
    )
    inverted = ShipBuildCombo(
        combo_id="combo_should_not_be_needed",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=None,
        beam_count=2,
        launcher_count=0,
        labels=("Serpent",),
        score_delta_2x=40,
        warship_delta=1,
        upper_bound=0,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(loss,),
            ship_build_combos=(inverted,),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id == loss.id
    assert result.solutions[0].ship_builds == ()


def test_solver_gift_vs_loss_are_distinct_and_gift_pins_counterparty():
    gift = CandidateAction(
        id=f"{GIFT_ACTION_PREFIX}warship:to:3:point:40",
        label="Gift warship to player 3",
        score_delta_2x=-40,
        warship_delta=-1,
        counterparty_player_id=3,
        prior_warship_usage=1,
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(gift,),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    action = result.solutions[0].actions[0]
    assert action.action_id == gift.id
    assert action.counterparty_player_id == 3


def test_solver_trade_class_flip_is_exact():
    trade = CandidateAction(
        id=f"{TRADE_ACTION_PREFIX}with:3",
        label="Trade with player 3",
        score_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=1,
        counterparty_player_id=3,
        prior_warship_usage=1,
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=1,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(trade,),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id.startswith(TRADE_ACTION_PREFIX)
    assert result.solutions[0].actions[0].counterparty_player_id == 3


def test_solver_acquired_ship_is_not_a_build_combo():
    acquired = CandidateAction(
        id=f"{ACQUIRED_SHIP_ACTION_PREFIX}warship:from:3",
        label="Acquired warship from player 3",
        score_delta_2x=40,
        warship_delta=1,
        counterparty_player_id=3,
        upper_bound=1,
    )
    build = ShipBuildCombo(
        combo_id="combo_build",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=None,
        beam_count=2,
        launcher_count=0,
        labels=("Serpent",),
        score_delta_2x=40,
        warship_delta=1,
        upper_bound=0,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=40,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(acquired,),
            ship_build_combos=(build,),
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id.startswith(ACQUIRED_SHIP_ACTION_PREFIX)
    assert result.solutions[0].ship_builds == ()


def test_envelope_military_interval_is_exact():
    loss = CandidateAction(
        id=f"{SHIP_LOSS_ACTION_PREFIX}warship:envelope:20:80",
        label="Ship loss (warship, envelope)",
        score_delta_2x=0,
        warship_delta=-1,
        score_delta_2x_min=-80,
        score_delta_2x_max=-20,
        prior_warship_usage=1,
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-50,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(loss,),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id == loss.id


def test_idle_dock_pp_equality_requires_ships_built_on_lattice():
    combo = ShipBuildCombo(
        combo_id="combo_one",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=None,
        beam_count=2,
        launcher_count=0,
        labels=("Serpent",),
        score_delta_2x=40,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=2,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=40,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=2,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(),
            ship_build_combos=(combo,),
            enforce_idle_dock_pp_equality=True,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    assert result.solutions[0].ship_builds[0].count == 1


def test_gift_and_loss_share_prior_fleet_departure_cap():
    gift = CandidateAction(
        id=f"{GIFT_ACTION_PREFIX}warship:to:3:point:40",
        label="Gift warship to player 3",
        score_delta_2x=-40,
        warship_delta=-1,
        counterparty_player_id=3,
        prior_warship_usage=1,
        upper_bound=1,
    )
    loss = CandidateAction(
        id=f"{SHIP_LOSS_ACTION_PREFIX}warship:point:40",
        label="Ship loss (warship)",
        score_delta_2x=-40,
        warship_delta=-1,
        prior_warship_usage=1,
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(gift, loss),
            prior_warship_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status == STATUS_EXACT
    for solution in result.solutions:
        used = sum(action.count for action in solution.actions)
        assert used == 1


def test_group_departure_cap_forbids_two_ship_trade_over_single_record_group():
    trade = CandidateAction(
        id=f"{TRADE_ACTION_PREFIX}warship:with:3:point:40",
        label="Trade warship with player 3",
        score_delta_2x=-80,
        warship_delta=-2,
        freighter_delta=2,
        counterparty_player_id=3,
        prior_warship_usage=2,
        prior_group_key="warship:point:40",
        upper_bound=1,
    )
    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-80,
        warship_delta=-2,
        freighter_delta=2,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    result = solve_inference_problem(
        InferenceProblem(
            observation=observation,
            aggregate_actions=(trade,),
            prior_warship_departure_cap=2,
            prior_departure_group_caps={"warship:point:40": 1},
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert result.status != STATUS_EXACT
    assert result.solutions == ()


def test_unpinned_gift_class_xor_allows_two_warship_groups_not_a_class_mix():
    exclusive_group = "gift:9"
    warship_a = CandidateAction(
        id=f"{GIFT_ACTION_PREFIX}warship:to:9:point:40",
        label="Gift warship to player 9",
        score_delta_2x=-40,
        warship_delta=-1,
        counterparty_player_id=9,
        prior_warship_usage=1,
        exclusive_class_group=exclusive_group,
        upper_bound=1,
    )
    warship_b = CandidateAction(
        id=f"{GIFT_ACTION_PREFIX}warship:to:9:point:50",
        label="Gift warship to player 9",
        score_delta_2x=-50,
        warship_delta=-1,
        counterparty_player_id=9,
        prior_warship_usage=1,
        exclusive_class_group=exclusive_group,
        upper_bound=1,
    )
    freighter = CandidateAction(
        id=f"{GIFT_ACTION_PREFIX}freighter:to:9:point:0",
        label="Gift freighter to player 9",
        score_delta_2x=0,
        freighter_delta=-1,
        counterparty_player_id=9,
        prior_freighter_usage=1,
        exclusive_class_group=exclusive_group,
        upper_bound=1,
    )
    both_warships = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-90,
        warship_delta=-2,
        freighter_delta=0,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    mixed_classes = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=-40,
        warship_delta=-1,
        freighter_delta=-1,
        priority_point_delta=1,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    actions = (warship_a, warship_b, freighter)
    same_class = solve_inference_problem(
        InferenceProblem(
            observation=both_warships,
            aggregate_actions=actions,
            prior_warship_departure_cap=2,
            prior_freighter_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert same_class.status == STATUS_EXACT
    chosen = {action.action_id for action in same_class.solutions[0].actions}
    assert chosen == {warship_a.id, warship_b.id}

    mixed = solve_inference_problem(
        InferenceProblem(
            observation=mixed_classes,
            aggregate_actions=actions,
            prior_warship_departure_cap=2,
            prior_freighter_departure_cap=1,
            max_solutions=5,
            time_limit_seconds=2.0,
        )
    )
    assert mixed.status == STATUS_NO_EXACT_SOLUTION
    assert mixed.solutions == ()
