"""OR-Tools CP-SAT adapter for military score build inference."""

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
)

STATUS_EXACT = "exact"
STATUS_INVALID_PROBLEM = "invalid_problem"
STATUS_NO_EXACT_SOLUTION = "no_exact_solution"


def _validate_problem(problem: InferenceProblem) -> str | None:
    seen_action_ids: set[str] = set()
    for action in problem.actions:
        if action.id in seen_action_ids:
            return f"duplicate action id: {action.id}"
        seen_action_ids.add(action.id)
        if action.lower_bound < 0:
            return f"action {action.id} has negative lower_bound"
        if action.lower_bound > action.upper_bound:
            return f"action {action.id} has lower_bound greater than upper_bound"
    return None


def _observation_has_no_deltas(problem: InferenceProblem) -> bool:
    observation = problem.observation
    return (
        observation.military_delta_2x == 0
        and observation.warship_delta == 0
        and observation.freighter_delta == 0
        and observation.priority_point_delta == 0
    )


def _extract_solution(
    problem: InferenceProblem,
    count_vars: dict[str, cp_model.IntVar],
    solver: cp_model.CpSolver,
) -> InferenceSolution:
    solution_actions: list[InferenceSolutionAction] = []
    objective_value = 0
    for action in problem.actions:
        count = solver.value(count_vars[action.id])
        if count == 0:
            continue
        solution_actions.append(
            InferenceSolutionAction(
                action_id=action.id,
                label=action.label,
                count=count,
            )
        )
        objective_value += action.probability_weight * count
    return InferenceSolution(
        objective_value=objective_value,
        actions=tuple(solution_actions),
    )


def solve_inference_problem(problem: InferenceProblem) -> InferenceResult:
    """Return one exact feasible solution when one exists, otherwise a structured status."""
    validation_error = _validate_problem(problem)
    if validation_error is not None:
        return InferenceResult(
            status=STATUS_INVALID_PROBLEM,
            solutions=(),
            diagnostics={"reason": validation_error},
        )

    if not problem.actions:
        if _observation_has_no_deltas(problem):
            return InferenceResult(
                status=STATUS_EXACT,
                solutions=(InferenceSolution(objective_value=0, actions=()),),
                diagnostics={"solver_status": "NO_ACTIONS"},
            )
        return InferenceResult(
            status=STATUS_NO_EXACT_SOLUTION,
            solutions=(),
            diagnostics={"reason": "no candidate actions for non-zero observation deltas"},
        )

    model = cp_model.CpModel()
    count_vars = {
        action.id: model.new_int_var(action.lower_bound, action.upper_bound, action.id)
        for action in problem.actions
    }
    observation = problem.observation

    model.add(
        sum(action.score_delta_2x * count_vars[action.id] for action in problem.actions)
        == observation.military_delta_2x
    )
    model.add(
        sum(action.warship_delta * count_vars[action.id] for action in problem.actions)
        == observation.warship_delta
    )
    model.add(
        sum(action.freighter_delta * count_vars[action.id] for action in problem.actions)
        == observation.freighter_delta
    )
    model.add(
        sum(action.priority_point_delta * count_vars[action.id] for action in problem.actions)
        == observation.priority_point_delta
    )
    model.add(
        sum(action.build_slot_usage * count_vars[action.id] for action in problem.actions)
        <= observation.starbases_owned
    )

    model.maximize(
        sum(action.probability_weight * count_vars[action.id] for action in problem.actions)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = problem.time_limit_seconds
    solver_status = solver.solve(model)

    if solver_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solution = _extract_solution(problem, count_vars, solver)
        return InferenceResult(
            status=STATUS_EXACT,
            solutions=(solution,),
            diagnostics={
                "solver_status": solver.status_name(solver_status),
                "wall_time_seconds": solver.wall_time,
            },
        )

    return InferenceResult(
        status=STATUS_NO_EXACT_SOLUTION,
        solutions=(),
        diagnostics={
            "solver_status": solver.status_name(solver_status),
            "wall_time_seconds": solver.wall_time,
        },
    )
