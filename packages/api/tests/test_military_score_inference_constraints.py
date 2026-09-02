"""Parity tests: CP-SAT hard constraints and diagnostic appliedEqualities stay aligned."""

from api.analytics.military_score_inference.constraints import (
    FIGHTER_TRANSFER_DIRECTIONS_EXCLUSIVE_DIAGNOSTIC,
    PRIORITY_POINT_DIAGNOSTIC_NOTE,
    InferenceHardConstraints,
    observation_to_constraints_payload,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
)
from api.analytics.military_score_inference.scoring import STARBASE_FIGHTER_SCORE_DELTA_2X
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    solve_inference_problem,
)


def _fighter_transfer_actions(*, upper_bound: int = 4) -> tuple[CandidateAction, CandidateAction]:
    starbase_to_ship = CandidateAction(
        id="fighters_starbase_to_ship",
        label="Fighters SB to ship",
        score_delta_2x=STARBASE_FIGHTER_SCORE_DELTA_2X,
        upper_bound=upper_bound,
    )
    ship_to_starbase = CandidateAction(
        id="fighters_ship_to_starbase",
        label="Fighters ship to SB",
        score_delta_2x=-STARBASE_FIGHTER_SCORE_DELTA_2X,
        upper_bound=upper_bound,
    )
    return starbase_to_ship, ship_to_starbase


def _action_count(solution, action_id: str) -> int:
    return next(
        (action.count for action in solution.actions if action.action_id == action_id),
        0,
    )


def _observation(
    *,
    military_delta_2x: int = 400,
    warship_delta: int = 1,
    freighter_delta: int = 0,
    priority_point_delta: int = 0,
    starbases_owned: int = 3,
    military_partition_slack_2x: int = 0,
) -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=priority_point_delta,
        starbases_owned=starbases_owned,
        is_after_ship_limit=False,
        military_partition_slack_2x=military_partition_slack_2x,
    )


def _build_warship_action(*, priority_point_delta: int = 0) -> CandidateAction:
    return CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=400,
        warship_delta=1,
        priority_point_delta=priority_point_delta,
        build_slot_usage=1,
        upper_bound=1,
    )


def _acquired_class_actions() -> tuple[CandidateAction, CandidateAction]:
    warship = CandidateAction(
        id="acquired:warship:from:3",
        label="Acquired warship from player 3",
        score_delta_2x=40,
        warship_delta=1,
        upper_bound=1,
    )
    freighter = CandidateAction(
        id="acquired:freighter:from:3",
        label="Acquired freighter from player 3",
        score_delta_2x=0,
        freighter_delta=1,
        upper_bound=1,
    )
    return warship, freighter


def test_applied_equalities_default_omit_priority_point():
    observation = _observation(priority_point_delta=54)
    constraints = InferenceHardConstraints()
    payload = observation_to_constraints_payload(observation, hard_constraints=constraints)

    assert constraints.enforced_equalities() == InferenceHardConstraints().enforced_equalities()
    assert payload["appliedEqualities"] == constraints.applied_equalities(observation)
    assert payload["priorityPointConstraintEnforced"] is False
    assert payload["priorityPointConstraintNote"] == PRIORITY_POINT_DIAGNOSTIC_NOTE
    assert not any("priorityPointDelta" in line for line in payload["appliedEqualities"])


def test_applied_equalities_from_problem_matches_hard_constraints_descriptor():
    observation = _observation(priority_point_delta=54)
    for enforce in (False, True):
        problem = InferenceProblem(
            observation=observation,
            aggregate_actions=(_build_warship_action(),),
            probability_buckets_by_action_id={},
            enforce_priority_point_constraint=enforce,
        )
        hard_constraints = InferenceHardConstraints.from_problem(problem)
        payload = observation_to_constraints_payload(observation, hard_constraints=hard_constraints)

        assert payload["appliedEqualities"] == hard_constraints.applied_equalities(observation)
        assert payload["priorityPointConstraintEnforced"] is enforce
        has_pp_line = any("priorityPointDelta" in line for line in payload["appliedEqualities"])
        assert has_pp_line is enforce
        if enforce:
            assert "priorityPointConstraintNote" not in payload
        else:
            assert payload["priorityPointConstraintNote"] == PRIORITY_POINT_DIAGNOSTIC_NOTE


def test_solver_behavior_tracks_enforced_priority_point_flag():
    """Shared descriptor: PP off is feasible, PP on is infeasible for this catalog."""
    build_action = _build_warship_action()
    observation = _observation(priority_point_delta=54)

    without_pp = InferenceProblem(
        observation=observation,
        aggregate_actions=(build_action,),
        probability_buckets_by_action_id={},
    )
    with_pp = InferenceProblem(
        observation=observation,
        aggregate_actions=(build_action,),
        probability_buckets_by_action_id={},
        enforce_priority_point_constraint=True,
    )

    assert solve_inference_problem(without_pp).status == STATUS_EXACT
    assert solve_inference_problem(with_pp).status == STATUS_NO_EXACT_SOLUTION

    without_payload = observation_to_constraints_payload(
        observation, hard_constraints=InferenceHardConstraints.from_problem(without_pp)
    )
    with_payload = observation_to_constraints_payload(
        observation, hard_constraints=InferenceHardConstraints.from_problem(with_pp)
    )
    assert without_payload["priorityPointConstraintEnforced"] is False
    assert with_payload["priorityPointConstraintEnforced"] is True
    assert len(with_payload["appliedEqualities"]) == len(without_payload["appliedEqualities"]) + 1


def test_enforced_priority_point_equality_satisfiable_when_catalog_matches():
    build_action = _build_warship_action(priority_point_delta=54)
    observation = _observation(priority_point_delta=54)
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(build_action,),
        probability_buckets_by_action_id={},
        enforce_priority_point_constraint=True,
    )
    result = solve_inference_problem(problem)
    payload = observation_to_constraints_payload(
        observation, hard_constraints=InferenceHardConstraints.from_problem(problem)
    )

    assert result.status == STATUS_EXACT
    assert any("priorityPointDelta" in line for line in payload["appliedEqualities"])


def test_military_score_band_constraint_allows_lower_explained_score():
    build_action = CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
    )
    observation = _observation(military_delta_2x=450, warship_delta=1)
    exact_problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(build_action,),
        probability_buckets_by_action_id={},
    )
    band_problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(build_action,),
        probability_buckets_by_action_id={},
        military_score_alpha=50,
    )

    assert solve_inference_problem(exact_problem).status == STATUS_NO_EXACT_SOLUTION
    assert solve_inference_problem(band_problem).status == STATUS_EXACT

    band_payload = observation_to_constraints_payload(
        observation,
        hard_constraints=InferenceHardConstraints.from_problem(band_problem),
    )
    assert band_payload["militaryScoreAlpha"] == 50
    assert any(">= 400" in line for line in band_payload["appliedEqualities"])


def test_scoreboard_partition_slack_allows_half_point_military_rounding():
    fighters = CandidateAction(
        id="starbase_fighters_added_total",
        label="Starbase fighters",
        score_delta_2x=STARBASE_FIGHTER_SCORE_DELTA_2X,
        upper_bound=5,
    )
    observation = _observation(
        military_delta_2x=624,
        warship_delta=0,
        freighter_delta=0,
        military_partition_slack_2x=1,
    )
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(fighters,),
        probability_buckets_by_action_id={},
    )

    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].count == 5

    payload = observation_to_constraints_payload(
        observation,
        hard_constraints=InferenceHardConstraints.from_problem(problem),
    )
    assert payload["militaryPartitionSlack2x"] == 1
    applied = payload["appliedEqualities"]
    assert any("623 <= sum(scoreDelta2x * count) <= 625" in line for line in applied)


def test_applied_equalities_include_fighter_transfer_exclusivity_when_both_actions_present():
    observation = _observation(military_delta_2x=0, warship_delta=0)
    starbase_to_ship, ship_to_starbase = _fighter_transfer_actions()
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(starbase_to_ship, ship_to_starbase),
        probability_buckets_by_action_id={},
    )
    hard_constraints = InferenceHardConstraints.from_problem(problem)
    aggregate_action_ids = frozenset(action.id for action in problem.aggregate_actions)

    payload = observation_to_constraints_payload(
        observation,
        hard_constraints=hard_constraints,
        aggregate_action_ids=aggregate_action_ids,
    )

    assert FIGHTER_TRANSFER_DIRECTIONS_EXCLUSIVE_DIAGNOSTIC in payload["appliedEqualities"]


def test_fighter_transfer_directions_are_mutually_exclusive():
    """Cancellation loops (SB->ship plus ship->SB) must not appear in any solution."""
    observation = _observation(military_delta_2x=0, warship_delta=0, freighter_delta=0)
    starbase_to_ship, ship_to_starbase = _fighter_transfer_actions(upper_bound=4)
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(starbase_to_ship, ship_to_starbase),
        probability_buckets_by_action_id={},
        max_solutions=50,
    )

    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    for solution in result.solutions:
        sb_to_ship = _action_count(solution, "fighters_starbase_to_ship")
        ship_to_sb = _action_count(solution, "fighters_ship_to_starbase")
        assert sb_to_ship == 0 or ship_to_sb == 0


def test_single_direction_fighter_transfer_still_satisfies_observation():
    starbase_to_ship, ship_to_starbase = _fighter_transfer_actions(upper_bound=4)
    for action, military_delta_2x in (
        (starbase_to_ship, 2 * STARBASE_FIGHTER_SCORE_DELTA_2X),
        (ship_to_starbase, -2 * STARBASE_FIGHTER_SCORE_DELTA_2X),
    ):
        observation = _observation(military_delta_2x=military_delta_2x, warship_delta=0)
        problem = InferenceProblem(
            observation=observation,
            aggregate_actions=(starbase_to_ship, ship_to_starbase),
            probability_buckets_by_action_id={},
        )
        result = solve_inference_problem(problem)
        assert result.status == STATUS_EXACT
        solution = result.solutions[0]
        assert _action_count(solution, action.id) == 2
        other_id = (
            "fighters_ship_to_starbase"
            if action.id == "fighters_starbase_to_ship"
            else "fighters_starbase_to_ship"
        )
        assert _action_count(solution, other_id) == 0


def test_acquired_class_cap_none_is_unconstrained_zero_hard_disallows():
    observation = _observation(military_delta_2x=40, warship_delta=1, freighter_delta=1)
    warship, freighter = _acquired_class_actions()
    blocked = InferenceProblem(
        observation=observation,
        aggregate_actions=(warship, freighter),
        acquired_warship_cap=1,
        acquired_freighter_cap=0,
        acquired_ship_cap=2,
    )
    open_classes = InferenceProblem(
        observation=observation,
        aggregate_actions=(warship, freighter),
        acquired_warship_cap=None,
        acquired_freighter_cap=None,
        acquired_ship_cap=2,
    )
    assert solve_inference_problem(blocked).status == STATUS_NO_EXACT_SOLUTION
    result = solve_inference_problem(open_classes)
    assert result.status == STATUS_EXACT
    assert _action_count(result.solutions[0], warship.id) == 1
    assert _action_count(result.solutions[0], freighter.id) == 1


def test_acquired_all_caps_zero_forbids_acquired():
    observation = _observation(military_delta_2x=40, warship_delta=1)
    warship, _ = _acquired_class_actions()
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(warship,),
        acquired_warship_cap=0,
        acquired_freighter_cap=0,
        acquired_ship_cap=0,
    )
    assert solve_inference_problem(problem).status == STATUS_NO_EXACT_SOLUTION


def test_acquired_cap_n_limits_acquired_count():
    observation = _observation(military_delta_2x=80, warship_delta=2)
    warship = CandidateAction(
        id="acquired:warship:from:3",
        label="Acquired warship from player 3",
        score_delta_2x=40,
        warship_delta=1,
        upper_bound=2,
    )
    capped = InferenceProblem(
        observation=observation,
        aggregate_actions=(warship,),
        acquired_warship_cap=1,
        acquired_ship_cap=2,
    )
    within_cap = InferenceProblem(
        observation=observation,
        aggregate_actions=(warship,),
        acquired_warship_cap=2,
        acquired_ship_cap=2,
    )
    assert solve_inference_problem(capped).status == STATUS_NO_EXACT_SOLUTION
    result = solve_inference_problem(within_cap)
    assert result.status == STATUS_EXACT
    assert _action_count(result.solutions[0], warship.id) == 2
