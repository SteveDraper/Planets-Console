"""OR-Tools CP-SAT adapter for military score build inference."""

import os
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import product
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken

from api.analytics.military_score_inference.constraints import InferenceHardConstraints
from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
    ProbabilityBucket,
    ShipBuildCombo,
)

STATUS_EXACT = "exact"
STATUS_INVALID_PROBLEM = "invalid_problem"
STATUS_NO_EXACT_SOLUTION = "no_exact_solution"
STATUS_STOPPED = "stopped"
STATUS_TIME_LIMITED = "time_limited"

_SUCCESS_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)


def _configured_num_search_workers(combo_count: int) -> int | None:
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS")
    if raw is not None:
        return int(raw)
    if combo_count > 100:
        return 8
    return None


@dataclass(frozen=True)
class _MergedComboCatalog:
    combos: tuple[ShipBuildCombo, ...]
    members_by_merged_id: dict[str, tuple[ShipBuildCombo, ...]]


@dataclass(frozen=True)
class _BuiltModel:
    model: cp_model.CpModel
    action_count_vars: dict[str, cp_model.IntVar]
    combo_count_vars: dict[str, cp_model.IntVar]
    bucket_vars_by_action_id: dict[str, tuple[cp_model.IntVar, ...]]
    merged_combo_catalog: _MergedComboCatalog


def _validate_problem(problem: InferenceProblem) -> str | None:
    seen_action_ids: set[str] = set()
    for action in problem.aggregate_actions:
        if action.id in seen_action_ids:
            return f"duplicate action id: {action.id}"
        seen_action_ids.add(action.id)
        if action.lower_bound < 0:
            return f"action {action.id} has negative lower_bound"
        if action.lower_bound > action.upper_bound:
            return f"action {action.id} has lower_bound greater than upper_bound"

    seen_combo_ids: set[str] = set()
    for combo in problem.ship_build_combos:
        if combo.combo_id in seen_combo_ids:
            return f"duplicate combo id: {combo.combo_id}"
        seen_combo_ids.add(combo.combo_id)
        if combo.lower_bound < 0:
            return f"combo {combo.combo_id} has negative lower_bound"
        if combo.lower_bound > combo.upper_bound:
            return f"combo {combo.combo_id} has lower_bound greater than upper_bound"

    for action_id, buckets in problem.probability_buckets_by_action_id.items():
        if action_id not in seen_action_ids:
            return f"unknown bucket action id: {action_id}"
        if not buckets:
            return f"empty probability buckets for action {action_id}"

        action = next(
            candidate for candidate in problem.aggregate_actions if candidate.id == action_id
        )
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


def _merge_score_equivalent_combos(
    combos: tuple[ShipBuildCombo, ...],
) -> _MergedComboCatalog:
    """Merge score-equivalent combos for CP-SAT feasibility; members kept for extraction."""
    groups: dict[tuple[int, int, int], list[ShipBuildCombo]] = defaultdict(list)
    for combo in combos:
        groups[(combo.score_delta_2x, combo.warship_delta, combo.freighter_delta)].append(combo)

    merged: list[ShipBuildCombo] = []
    members_by_merged_id: dict[str, tuple[ShipBuildCombo, ...]] = {}
    for members in groups.values():
        sorted_members = tuple(sorted(members, key=lambda combo: combo.combo_id))
        if len(sorted_members) == 1:
            combo = sorted_members[0]
            merged.append(combo)
            members_by_merged_id[combo.combo_id] = sorted_members
            continue

        representative = max(
            sorted_members,
            key=lambda combo: (combo.probability_weight, combo.combo_id),
        )
        merged_id = (
            f"combo_equiv_{representative.score_delta_2x}_"
            f"{representative.warship_delta}_{representative.freighter_delta}"
        )
        merged.append(
            replace(
                representative,
                combo_id=merged_id,
                labels=tuple(label for member in sorted_members for label in member.labels),
                probability_weight=max(member.probability_weight for member in sorted_members),
                upper_bound=max(member.upper_bound for member in sorted_members),
            )
        )
        members_by_merged_id[merged_id] = sorted_members

    return _MergedComboCatalog(
        combos=tuple(merged),
        members_by_merged_id=members_by_merged_id,
    )


def _observation_is_solver_idle(problem: InferenceProblem) -> bool:
    """True when the solver has no modeled deltas to explain."""
    observation = problem.observation
    if (
        observation.military_delta_2x != 0
        or observation.warship_delta != 0
        or observation.freighter_delta != 0
    ):
        return False
    if observation.priority_point_delta == 0:
        return True
    return not problem.enforce_priority_point_constraint


def _problem_has_catalog_entries(problem: InferenceProblem) -> bool:
    return bool(problem.aggregate_actions or problem.ship_build_combos)


def _build_model(
    problem: InferenceProblem,
    merged_combo_catalog: _MergedComboCatalog,
) -> _BuiltModel:
    model = cp_model.CpModel()
    action_count_vars = {
        action.id: model.new_int_var(action.lower_bound, action.upper_bound, action.id)
        for action in problem.aggregate_actions
    }
    combo_count_vars = {
        combo.combo_id: model.new_int_var(combo.lower_bound, combo.upper_bound, combo.combo_id)
        for combo in merged_combo_catalog.combos
    }
    bucket_vars_by_action_id: dict[str, tuple[cp_model.IntVar, ...]] = {}
    objective_terms: list[cp_model.LinearExpr] = []

    for action in problem.aggregate_actions:
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
            model.add(action_count_vars[action.id] == sum(bucket_vars))
        else:
            objective_terms.append(action_count_vars[action.id] * action.probability_weight)

    for combo in merged_combo_catalog.combos:
        objective_terms.append(combo_count_vars[combo.combo_id] * combo.probability_weight)

    merged_problem = replace(problem, ship_build_combos=merged_combo_catalog.combos)
    InferenceHardConstraints.from_problem(merged_problem).add_to_model(
        model,
        merged_problem,
        action_count_vars,
        combo_count_vars,
    )
    model.maximize(sum(objective_terms))
    return _BuiltModel(
        model=model,
        action_count_vars=action_count_vars,
        combo_count_vars=combo_count_vars,
        bucket_vars_by_action_id=bucket_vars_by_action_id,
        merged_combo_catalog=merged_combo_catalog,
    )


def _read_action_counts(
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
    solver: cp_model.CpSolver,
) -> dict[str, int]:
    return {
        action.id: solver.value(action_count_vars[action.id])
        for action in problem.aggregate_actions
    }


def _read_combo_counts(
    merged_combo_catalog: _MergedComboCatalog,
    combo_count_vars: dict[str, cp_model.IntVar],
    solver: cp_model.CpSolver,
) -> dict[str, int]:
    return {
        combo.combo_id: solver.value(combo_count_vars[combo.combo_id])
        for combo in merged_combo_catalog.combos
    }


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
    ship_builds: tuple[InferenceSolutionShipBuild, ...],
    bucket_counts_by_action_id: dict[str, tuple[int, ...]],
    *,
    combo_probability_weight_by_id: dict[str, int],
) -> int:
    objective_value = 0
    for action in problem.aggregate_actions:
        buckets = problem.probability_buckets_by_action_id.get(action.id)
        if buckets:
            bucket_counts = bucket_counts_by_action_id[action.id]
            for bucket, count in zip(buckets, bucket_counts, strict=True):
                objective_value += bucket.marginal_weight * count
        else:
            objective_value += action.probability_weight * action_counts[action.id]
    for ship_build in ship_builds:
        objective_value += combo_probability_weight_by_id[ship_build.combo_id] * ship_build.count
    return objective_value


def _ship_build_from_member(
    member: ShipBuildCombo,
    count: int,
) -> InferenceSolutionShipBuild:
    return InferenceSolutionShipBuild(
        combo_id=member.combo_id,
        label=member.labels[0],
        count=count,
        hull_id=member.hull_id,
        engine_id=member.engine_id,
        beam_id=member.beam_id,
        torp_id=member.torp_id,
        beam_count=member.beam_count,
        launcher_count=member.launcher_count,
    )


def _ship_build_variants_for_merged_count(
    merged_combo_id: str,
    count: int,
    merged_combo_catalog: _MergedComboCatalog,
) -> tuple[InferenceSolutionShipBuild, ...]:
    members = merged_combo_catalog.members_by_merged_id[merged_combo_id]
    if len(members) == 1:
        return (_ship_build_from_member(members[0], count),)

    distinct_weights = {member.probability_weight for member in members}
    if len(distinct_weights) <= 1:
        representative = max(members, key=lambda member: member.combo_id)
        return (_ship_build_from_member(representative, count),)

    by_weight: dict[int, list[ShipBuildCombo]] = defaultdict(list)
    for member in members:
        by_weight[member.probability_weight].append(member)
    return tuple(
        _ship_build_from_member(max(group, key=lambda member: member.combo_id), count)
        for group in by_weight.values()
    )


def _expand_score_equivalent_solutions(
    problem: InferenceProblem,
    action_counts: dict[str, int],
    combo_counts: dict[str, int],
    bucket_counts_by_action_id: dict[str, tuple[int, ...]],
    merged_combo_catalog: _MergedComboCatalog,
) -> list[InferenceSolution]:
    action_by_id = {action.id: action for action in problem.aggregate_actions}
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
    ship_build_variant_lists = [
        _ship_build_variants_for_merged_count(merged_combo_id, count, merged_combo_catalog)
        for merged_combo_id, count in combo_counts.items()
        if count > 0
    ]
    combo_probability_weight_by_id = {
        combo.combo_id: combo.probability_weight for combo in problem.ship_build_combos
    }
    solutions: list[InferenceSolution] = []
    for ship_build_variant in product(*ship_build_variant_lists):
        ship_builds = tuple(ship_build_variant)
        solutions.append(
            InferenceSolution(
                objective_value=_objective_value(
                    problem,
                    action_counts,
                    ship_builds,
                    bucket_counts_by_action_id,
                    combo_probability_weight_by_id=combo_probability_weight_by_id,
                ),
                actions=tuple(solution_actions),
                ship_builds=ship_builds,
            )
        )
    return solutions


def _add_no_good_cut(
    model: cp_model.CpModel,
    action_count_vars: dict[str, cp_model.IntVar],
    combo_count_vars: dict[str, cp_model.IntVar],
    action_counts: dict[str, int],
    combo_counts: dict[str, int],
    cut_index: int,
) -> None:
    differs: list[cp_model.IntVar] = []
    for action_id, previous_count in action_counts.items():
        differs_from_previous = model.new_bool_var(f"diff_{cut_index}_{action_id}")
        model.add(action_count_vars[action_id] != previous_count).only_enforce_if(
            differs_from_previous
        )
        model.add(action_count_vars[action_id] == previous_count).only_enforce_if(
            differs_from_previous.Not()
        )
        differs.append(differs_from_previous)
    for combo_id, previous_count in combo_counts.items():
        differs_from_previous = model.new_bool_var(f"diff_{cut_index}_{combo_id}")
        model.add(combo_count_vars[combo_id] != previous_count).only_enforce_if(
            differs_from_previous
        )
        model.add(combo_count_vars[combo_id] == previous_count).only_enforce_if(
            differs_from_previous.Not()
        )
        differs.append(differs_from_previous)
    model.add_at_least_one(differs)


def solution_signature(solution: InferenceSolution) -> tuple[tuple[str, int], ...]:
    action_counts = ((action.action_id, action.count) for action in solution.actions)
    combo_counts = ((build.combo_id, build.count) for build in solution.ship_builds)
    return tuple(sorted(action_counts) + sorted(combo_counts))


class _StopSearchOnCancel(cp_model.CpSolverSolutionCallback):
    def __init__(self, cancel_token: InferenceCancelToken) -> None:
        super().__init__()
        self._cancel_token = cancel_token

    def on_solution_callback(self) -> None:
        if self._cancel_token.is_cancelled():
            self.StopSearch()


def solve_inference_problem(
    problem: InferenceProblem,
    *,
    on_solution: Callable[[InferenceSolution], None] | None = None,
    cancel_token: InferenceCancelToken | None = None,
) -> InferenceResult:
    """Return up to max_solutions ranked feasible explanations for one player turn."""
    validation_error = _validate_problem(problem)
    if validation_error is not None:
        return InferenceResult(
            status=STATUS_INVALID_PROBLEM,
            solutions=(),
            diagnostics={"reason": validation_error},
        )

    if not _problem_has_catalog_entries(problem):
        if _observation_is_solver_idle(problem):
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

    merged_combo_catalog = _merge_score_equivalent_combos(problem.ship_build_combos)
    built_model = _build_model(problem, merged_combo_catalog)
    model = built_model.model
    action_count_vars = built_model.action_count_vars
    combo_count_vars = built_model.combo_count_vars
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
        if cancel_token is not None and cancel_token.is_cancelled():
            stopped_reason = "cancelled"
            break

        elapsed_seconds = time.monotonic() - started_at
        remaining_seconds = problem.time_limit_seconds - elapsed_seconds
        if remaining_seconds <= 0:
            time_limited = True
            stopped_reason = "time_budget"
            break

        solver.parameters.max_time_in_seconds = remaining_seconds
        num_search_workers = _configured_num_search_workers(len(problem.ship_build_combos))
        if num_search_workers is not None:
            solver.parameters.num_search_workers = num_search_workers
        if cancel_token is not None:
            callback = _StopSearchOnCancel(cancel_token)
            last_solver_status = solver.solve(model, callback)
        else:
            last_solver_status = solver.solve(model)

        if cancel_token is not None and cancel_token.is_cancelled():
            stopped_reason = "cancelled"
            break
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

        action_counts = _read_action_counts(problem, action_count_vars, solver)
        combo_counts = _read_combo_counts(merged_combo_catalog, combo_count_vars, solver)
        bucket_counts = _read_bucket_counts(bucket_vars_by_action_id, solver)
        expanded_solutions = _expand_score_equivalent_solutions(
            problem,
            action_counts,
            combo_counts,
            bucket_counts,
            merged_combo_catalog,
        )
        expanded_solutions.sort(key=lambda solution: solution.objective_value, reverse=True)
        added_solution = False
        for solution in expanded_solutions:
            if len(solutions) >= problem.max_solutions:
                stopped_reason = "max_solutions"
                break
            signature = solution_signature(solution)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            solutions.append(solution)
            top_solution_bucket_counts = bucket_counts
            added_solution = True
            if on_solution is not None:
                on_solution(solution)

        if stopped_reason == "max_solutions":
            break
        if not added_solution:
            stopped_reason = "duplicate_solution"
            break

        _add_no_good_cut(
            model,
            action_count_vars,
            combo_count_vars,
            action_counts,
            combo_counts,
            len(solutions),
        )

        if len(solutions) >= problem.max_solutions:
            stopped_reason = "max_solutions"
            break

    diagnostics: dict[str, object] = {
        "solver_status": solver.status_name(last_solver_status),
        "solution_count": len(solutions),
        "stopped_reason": stopped_reason,
        "wall_time_seconds": time.monotonic() - started_at,
        "policy_step_id": problem.policy_step_id,
        "policy_step_index": problem.policy_step_index,
        "military_score_alpha": problem.military_score_alpha,
    }
    if time_limited:
        diagnostics["time_limited"] = True
    if top_solution_bucket_counts:
        diagnostics["bucket_counts_by_action_id"] = top_solution_bucket_counts

    if solutions:
        solutions.sort(key=lambda solution: solution.objective_value, reverse=True)

    if stopped_reason == "cancelled":
        status = STATUS_STOPPED
    elif not solutions:
        status = STATUS_TIME_LIMITED if time_limited else STATUS_NO_EXACT_SOLUTION
    else:
        status = STATUS_TIME_LIMITED if time_limited else STATUS_EXACT

    return InferenceResult(status=status, solutions=tuple(solutions), diagnostics=diagnostics)
