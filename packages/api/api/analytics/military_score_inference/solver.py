"""OR-Tools CP-SAT adapter for military score build inference."""

import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.constraints import InferenceHardConstraints
from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
    ProbabilityBucket,
)

STATUS_EXACT = "exact"
STATUS_INVALID_PROBLEM = "invalid_problem"
STATUS_NO_EXACT_SOLUTION = "no_exact_solution"
STATUS_TIME_LIMITED = "time_limited"

_SUCCESS_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)


@dataclass(frozen=True)
class _BuiltModel:
    model: cp_model.CpModel
    count_vars: dict[str, cp_model.IntVar]
    bucket_vars_by_action_id: dict[str, tuple[cp_model.IntVar, ...]]


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

    for action_id, buckets in problem.probability_buckets_by_action_id.items():
        if action_id not in seen_action_ids:
            return f"unknown bucket action id: {action_id}"
        if not buckets:
            return f"empty probability buckets for action {action_id}"

        action = next(candidate for candidate in problem.actions if candidate.id == action_id)
        previous_upper_count = -1
        total_bucket_capacity = 0
        for bucket in buckets:
            if bucket.lower_count > bucket.upper_count:
                return f"bucket {bucket.label} for action {action_id} has invalid count range"
            if bucket.lower_count <= previous_upper_count:
                return f"bucket {bucket.label} for action {action_id} overlaps prior bucket"
            previous_upper_count = bucket.upper_count
            total_bucket_capacity += _bucket_capacity(bucket)

        if total_bucket_capacity < action.upper_bound:
            return (
                f"probability buckets for action {action_id} "
                f"cover only {total_bucket_capacity} counts but upper_bound is {action.upper_bound}"
            )

    return None


def _bucket_capacity(bucket: ProbabilityBucket) -> int:
    if bucket.lower_count == 0:
        return bucket.upper_count
    return bucket.upper_count - bucket.lower_count + 1


def _observation_has_no_deltas(problem: InferenceProblem) -> bool:
    observation = problem.observation
    return (
        observation.military_delta_2x == 0
        and observation.warship_delta == 0
        and observation.freighter_delta == 0
        and observation.priority_point_delta == 0
    )


def _build_model(problem: InferenceProblem) -> _BuiltModel:
    model = cp_model.CpModel()
    count_vars = {
        action.id: model.new_int_var(action.lower_bound, action.upper_bound, action.id)
        for action in problem.actions
    }
    bucket_vars_by_action_id: dict[str, tuple[cp_model.IntVar, ...]] = {}
    objective_terms: list[cp_model.LinearExpr] = []

    for action in problem.actions:
        buckets = problem.probability_buckets_by_action_id.get(action.id)
        if buckets:
            bucket_vars: list[cp_model.IntVar] = []
            for index, bucket in enumerate(buckets):
                bucket_var = model.new_int_var(
                    0,
                    _bucket_capacity(bucket),
                    f"{action.id}_bucket_{index}",
                )
                bucket_vars.append(bucket_var)
                objective_terms.append(bucket_var * bucket.marginal_weight)
            bucket_vars_by_action_id[action.id] = tuple(bucket_vars)
            model.add(count_vars[action.id] == sum(bucket_vars))
        else:
            objective_terms.append(count_vars[action.id] * action.probability_weight)

    InferenceHardConstraints.from_problem(problem).add_to_model(model, problem, count_vars)
    model.maximize(sum(objective_terms))
    return _BuiltModel(
        model=model,
        count_vars=count_vars,
        bucket_vars_by_action_id=bucket_vars_by_action_id,
    )


def _read_action_counts(
    problem: InferenceProblem,
    count_vars: dict[str, cp_model.IntVar],
    solver: cp_model.CpSolver,
) -> dict[str, int]:
    return {action.id: solver.value(count_vars[action.id]) for action in problem.actions}


def _read_bucket_counts(
    bucket_vars_by_action_id: dict[str, tuple[cp_model.IntVar, ...]],
    solver: cp_model.CpSolver,
) -> dict[str, tuple[int, ...]]:
    return {
        action_id: tuple(solver.value(bucket_var) for bucket_var in bucket_vars)
        for action_id, bucket_vars in bucket_vars_by_action_id.items()
    }


def _objective_value(
    problem: InferenceProblem,
    action_counts: dict[str, int],
    bucket_counts_by_action_id: dict[str, tuple[int, ...]],
) -> int:
    objective_value = 0
    for action in problem.actions:
        buckets = problem.probability_buckets_by_action_id.get(action.id)
        if buckets:
            bucket_counts = bucket_counts_by_action_id[action.id]
            for bucket, count in zip(buckets, bucket_counts, strict=True):
                objective_value += bucket.marginal_weight * count
        else:
            objective_value += action.probability_weight * action_counts[action.id]
    return objective_value


def _extract_solution(
    problem: InferenceProblem,
    action_counts: dict[str, int],
    bucket_counts_by_action_id: dict[str, tuple[int, ...]],
) -> InferenceSolution:
    action_by_id = {action.id: action for action in problem.actions}
    solution_actions: list[InferenceSolutionAction] = []
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
    return InferenceSolution(
        objective_value=_objective_value(problem, action_counts, bucket_counts_by_action_id),
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

    built_model = _build_model(problem)
    model = built_model.model
    count_vars = built_model.count_vars
    bucket_vars_by_action_id = built_model.bucket_vars_by_action_id
    solver = cp_model.CpSolver()
    solutions: list[InferenceSolution] = []
    seen_signatures: set[tuple[tuple[str, int], ...]] = set()
    started_at = time.monotonic()
    last_solver_status = cp_model.UNKNOWN
    stopped_reason = "exhausted"
    time_limited = False
    top_solution_bucket_counts: dict[str, tuple[int, ...]] = {}

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
        bucket_counts = _read_bucket_counts(bucket_vars_by_action_id, solver)
        solution = _extract_solution(problem, action_counts, bucket_counts)
        signature = _solution_signature(solution)
        if signature in seen_signatures:
            stopped_reason = "duplicate_solution"
            break

        seen_signatures.add(signature)
        solutions.append(solution)
        top_solution_bucket_counts = bucket_counts
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
    if top_solution_bucket_counts:
        diagnostics["bucket_counts_by_action_id"] = top_solution_bucket_counts

    if not solutions:
        status = STATUS_TIME_LIMITED if time_limited else STATUS_NO_EXACT_SOLUTION
        return InferenceResult(status=status, solutions=(), diagnostics=diagnostics)

    solutions.sort(key=lambda solution: solution.objective_value, reverse=True)
    status = STATUS_TIME_LIMITED if time_limited else STATUS_EXACT
    return InferenceResult(status=status, solutions=tuple(solutions), diagnostics=diagnostics)
