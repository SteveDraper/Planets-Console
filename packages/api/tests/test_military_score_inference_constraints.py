"""Parity tests: CP-SAT hard constraints and diagnostic appliedEqualities stay aligned."""

from api.analytics.military_score_inference.constraints import (
    PRIORITY_POINT_DIAGNOSTIC_NOTE,
    InferenceHardConstraints,
    observation_to_constraints_payload,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    solve_inference_problem,
)


def _observation(
    *,
    military_delta_2x: int = 400,
    warship_delta: int = 1,
    freighter_delta: int = 0,
    priority_point_delta: int = 0,
    starbases_owned: int = 3,
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
        probability_weight=100,
    )


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
            actions=(_build_warship_action(),),
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
        actions=(build_action,),
        probability_buckets_by_action_id={},
    )
    with_pp = InferenceProblem(
        observation=observation,
        actions=(build_action,),
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
        actions=(build_action,),
        probability_buckets_by_action_id={},
        enforce_priority_point_constraint=True,
    )
    result = solve_inference_problem(problem)
    payload = observation_to_constraints_payload(
        observation, hard_constraints=InferenceHardConstraints.from_problem(problem)
    )

    assert result.status == STATUS_EXACT
    assert any("priorityPointDelta" in line for line in payload["appliedEqualities"])
