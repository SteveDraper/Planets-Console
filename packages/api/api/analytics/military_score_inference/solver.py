"""OR-Tools CP-SAT adapter for military score build inference."""

import time

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
STATUS_TIME_LIMITED = "time_limited"

_SUCCESS_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)


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


def _build_model(
    problem: InferenceProblem,
) -> tuple[cp_model.CpModel, dict[str, cp_model.IntVar]]:
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
    return model, count_vars


def _read_action_counts(
    problem: InferenceProblem,
    count_vars: dict[str, cp_model.IntVar],
    solver: cp_model.CpSolver,
) -> dict[str, int]:
    return {action.id: solver.value(count_vars[action.id]) for action in problem.actions}


def _extract_solution(
    problem: InferenceProblem,
    action_counts: dict[str, int],
) -> InferenceSolution:
    action_by_id = {action.id: action for action in problem.actions}
    solution_actions: list[InferenceSolutionAction] = []
    objective_value = 0
    for action_id, count in action_counts.items():
        if count == 0:
            continue
        action = action_by_id[action_id]
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


def _add_no_good_cut(
    model: cp_model.CpModel,
    count_vars: dict[str, cp_model.IntVar],
    action_counts: dict[str, int],
    cut_index: int,
) -> None:
    differs: list[cp_model.IntVar] = []
    for action_id, previous_count in action_counts.items():
        differs_from_previous = model.new_bool_var(f"diff_{cut_index}_{action_id}")
        model.add(count_vars[action_id] != previous_count).only_enforce_if(differs_from_previous)
        model.add(count_vars[action_id] == previous_count).only_enforce_if(
            differs_from_previous.Not()
        )
        differs.append(differs_from_previous)
    model.add_at_least_one(differs)


def _solution_signature(solution: InferenceSolution) -> tuple[tuple[str, int], ...]:
    counts = ((action.action_id, action.count) for action in solution.actions)
    return tuple(sorted(counts))


def solve_inference_problem(problem: InferenceProblem) -> InferenceResult:
    """Return up to max_solutions ranked feasible explanations for one player turn."""
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
                diagnostics={"solver_status": "NO_ACTIONS", "solution_count": 1},
            )
        return InferenceResult(
            status=STATUS_NO_EXACT_SOLUTION,
            solutions=(),
            diagnostics={"reason": "no candidate actions for non-zero observation deltas"},
        )

    model, count_vars = _build_model(problem)
    solver = cp_model.CpSolver()
    solutions: list[InferenceSolution] = []
    seen_signatures: set[tuple[tuple[str, int], ...]] = set()
    started_at = time.monotonic()
    last_solver_status = cp_model.UNKNOWN
    stopped_reason = "exhausted"
    time_limited = False

    while len(solutions) < problem.max_solutions:
        elapsed_seconds = time.monotonic() - started_at
        remaining_seconds = problem.time_limit_seconds - elapsed_seconds
        if remaining_seconds <= 0:
            time_limited = True
            stopped_reason = "time_budget"
            break

        solver.parameters.max_time_in_seconds = remaining_seconds
        last_solver_status = solver.solve(model)
        if last_solver_status not in _SUCCESS_STATUSES:
            if last_solver_status == cp_model.UNKNOWN and solutions:
                time_limited = True
                stopped_reason = "time_budget"
            elif not solutions:
                stopped_reason = "infeasible"
            else:
                stopped_reason = "infeasible"
            break

        if last_solver_status == cp_model.FEASIBLE:
            elapsed_seconds = time.monotonic() - started_at
            if elapsed_seconds >= problem.time_limit_seconds:
                time_limited = True
                stopped_reason = "time_budget"

        action_counts = _read_action_counts(problem, count_vars, solver)
        solution = _extract_solution(problem, action_counts)
        signature = _solution_signature(solution)
        if signature in seen_signatures:
            stopped_reason = "duplicate_solution"
            break

        seen_signatures.add(signature)
        solutions.append(solution)
        _add_no_good_cut(model, count_vars, action_counts, len(solutions))

        if len(solutions) >= problem.max_solutions:
            stopped_reason = "max_solutions"
            break

    diagnostics: dict[str, object] = {
        "solver_status": solver.status_name(last_solver_status),
        "solution_count": len(solutions),
        "stopped_reason": stopped_reason,
        "wall_time_seconds": time.monotonic() - started_at,
    }
    if time_limited:
        diagnostics["time_limited"] = True

    if not solutions:
        status = STATUS_TIME_LIMITED if time_limited else STATUS_NO_EXACT_SOLUTION
        return InferenceResult(status=status, solutions=(), diagnostics=diagnostics)

    solutions.sort(key=lambda solution: solution.objective_value, reverse=True)
    status = STATUS_TIME_LIMITED if time_limited else STATUS_EXACT
    return InferenceResult(status=status, solutions=tuple(solutions), diagnostics=diagnostics)
