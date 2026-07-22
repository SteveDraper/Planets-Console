"""OR-Tools CP-SAT adapter for military score build inference."""

import os
import time
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from itertools import product
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken

from api.analytics.military_score_inference.constraints import InferenceHardConstraints
from api.analytics.military_score_inference.inference_objective import (
    build_inference_objective_terms,
    max_combo_probability_weight,
)
from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.ranking_heuristics import (
    compute_bin_penalty_objective_contribution,
    compute_overflow_objective_contribution,
    compute_partial_weapon_slot_penalty_contribution,
    ranking_heuristics_diagnostics_payload,
    ranking_penalty_from_marginal_weight,
)
from api.analytics.military_score_inference.ship_build_combos import (
    is_generic_zero_military_score_combo_id,
)
from api.concepts.races import is_horwasp

STATUS_EXACT = "exact"
STATUS_INVALID_PROBLEM = "invalid_problem"
STATUS_NO_EXACT_SOLUTION = "no_exact_solution"
STATUS_STOPPED = "stopped"
STATUS_TIME_LIMITED = "time_limited"

_SUCCESS_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)

# Ranking objective domain for the exposed IntVar used by near-best banding.
_RANKING_OBJECTIVE_VAR_LB = -10_000_000
_RANKING_OBJECTIVE_VAR_UB = 1_000_000


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
    objective_var: cp_model.IntVar
    merged_combo_catalog: _MergedComboCatalog
    diversity_caps_applied: tuple[dict[str, object], ...]


def _solver_build_diagnostics(
    problem: InferenceProblem,
    built_model: _BuiltModel,
) -> dict[str, object]:
    """Diagnostics fixed at CP-SAT model build time; merged into InferenceResult.diagnostics."""
    return {
        "rankingHeuristics": ranking_heuristics_diagnostics_payload(
            problem.ranking_heuristics,
            admission_caps_by_action_id=problem.admission_caps_by_action_id,
        ),
        "diversityCapsApplied": list(built_model.diversity_caps_applied),
    }


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
        for bucket in buckets:
            if bucket.lower_count > bucket.upper_count:
                return f"bucket {bucket.label} for action {action_id} has invalid count range"
            if bucket.lower_count <= previous_upper_count:
                return f"bucket {bucket.label} for action {action_id} overlaps prior bucket"
            previous_upper_count = bucket.upper_count

        max_covered_count = buckets[-1].upper_count
        overflow_band = problem.tier_overflow_by_action_id.get(action_id)
        if overflow_band is not None:
            max_covered_count = max(max_covered_count, overflow_band.current_cap)

        if max_covered_count < action.upper_bound:
            return (
                f"probability buckets for action {action_id} "
                f"cover only {max_covered_count} counts but upper_bound is {action.upper_bound}"
            )

    return None


def _merge_score_equivalent_combos(
    combos: tuple[ShipBuildCombo, ...],
) -> _MergedComboCatalog:
    """Merge score-equivalent combos for CP-SAT feasibility; members kept for extraction."""
    groups: dict[tuple[int, int, int], list[ShipBuildCombo]] = defaultdict(list)
    merged: list[ShipBuildCombo] = []
    members_by_merged_id: dict[str, tuple[ShipBuildCombo, ...]] = {}
    for combo in combos:
        if is_generic_zero_military_score_combo_id(combo.combo_id):
            merged.append(combo)
            members_by_merged_id[combo.combo_id] = (combo,)
            continue
        groups[(combo.score_delta_2x, combo.warship_delta, combo.freighter_delta)].append(combo)

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


def _freighter_only_zero_military_solution(
    problem: InferenceProblem,
) -> InferenceSolution | None:
    """Return a ship-only freighter explanation without CP-SAT when constraints allow."""
    observation = problem.observation
    if (
        observation.military_delta_2x != 0
        or observation.warship_delta != 0
        or observation.freighter_delta <= 0
    ):
        return None
    if observation.priority_point_delta != 0 and problem.enforce_priority_point_constraint:
        return None
    if any(action.lower_bound > 0 for action in problem.aggregate_actions):
        return None
    freighter_combo = next(
        (
            combo
            for combo in problem.ship_build_combos
            if is_generic_zero_military_score_combo_id(combo.combo_id)
        ),
        None,
    )
    if freighter_combo is None or freighter_combo.upper_bound < observation.freighter_delta:
        return None
    ship_build = _ship_build_from_member(freighter_combo, observation.freighter_delta)
    return InferenceSolution(
        objective_value=_objective_value(problem, {}, (ship_build,)),
        actions=(),
        ship_builds=(ship_build,),
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
    objective_terms = build_inference_objective_terms(
        model,
        problem,
        action_count_vars,
        combo_count_vars,
        ship_build_combos=merged_combo_catalog.combos,
    )

    merged_problem = replace(problem, ship_build_combos=merged_combo_catalog.combos)
    diversity_caps_applied = InferenceHardConstraints.from_problem(merged_problem).add_to_model(
        model,
        merged_problem,
        action_count_vars,
        combo_count_vars,
    )
    objective_var = model.new_int_var(
        _RANKING_OBJECTIVE_VAR_LB,
        _RANKING_OBJECTIVE_VAR_UB,
        "ranking_objective",
    )
    if objective_terms:
        model.add(objective_var == sum(objective_terms))
    else:
        model.add(objective_var == 0)
    model.maximize(objective_var)
    return _BuiltModel(
        model=model,
        action_count_vars=action_count_vars,
        combo_count_vars=combo_count_vars,
        objective_var=objective_var,
        merged_combo_catalog=merged_combo_catalog,
        diversity_caps_applied=tuple(diversity_caps_applied),
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


def _ranking_bin_indicators_by_action_id(
    problem: InferenceProblem,
    action_counts: dict[str, int],
) -> dict[str, tuple[int, ...]]:
    from api.analytics.military_score_inference.ranking_heuristics import (
        active_ranking_bin_indicators,
    )

    return {
        action_id: active_ranking_bin_indicators(action_counts.get(action_id, 0), buckets)
        for action_id, buckets in problem.probability_buckets_by_action_id.items()
    }


def _objective_value(
    problem: InferenceProblem,
    action_counts: dict[str, int],
    ship_builds: tuple[InferenceSolutionShipBuild, ...],
) -> int:
    max_combo_weight = max_combo_probability_weight(problem)
    # The bin penalty naturally includes the occurrence cost: active positive bins
    # sit below the none max-weight bin, so no separate parsimony term is needed.
    objective_value = compute_bin_penalty_objective_contribution(
        action_counts,
        problem.probability_buckets_by_action_id,
    )
    objective_value += compute_overflow_objective_contribution(
        action_counts,
        problem.tier_overflow_by_action_id,
    )
    combo_by_id = {combo.combo_id: combo for combo in problem.ship_build_combos}
    for ship_build in ship_builds:
        combo = combo_by_id[ship_build.combo_id]
        combo_penalty = ranking_penalty_from_marginal_weight(
            combo.probability_weight,
            max_marginal_weight=max_combo_weight,
        )
        objective_value -= combo_penalty * ship_build.count
    objective_value += compute_partial_weapon_slot_penalty_contribution(
        ship_builds,
        combo_by_id,
        problem.ranking_heuristics,
    )
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


def _ranked_merged_members(members: tuple[ShipBuildCombo, ...]) -> tuple[ShipBuildCombo, ...]:
    """Order equivalent combos for expansion: highest probability first, then combo id."""
    return tuple(sorted(members, key=lambda member: (-member.probability_weight, member.combo_id)))


def _ship_build_variants_for_merged_count(
    merged_combo_id: str,
    count: int,
    merged_combo_catalog: _MergedComboCatalog,
    *,
    max_expansions: int,
) -> tuple[InferenceSolutionShipBuild, ...]:
    members = merged_combo_catalog.members_by_merged_id[merged_combo_id]
    if is_generic_zero_military_score_combo_id(merged_combo_id):
        return (_ship_build_from_member(members[0], count),)
    if len(members) == 1:
        return (_ship_build_from_member(members[0], count),)

    if count != 1:
        best_member = _ranked_merged_members(members)[0]
        return (_ship_build_from_member(best_member, count),)

    ranked_members = _ranked_merged_members(members)
    expansion_limit = max(1, max_expansions)
    return tuple(
        _ship_build_from_member(member, count) for member in ranked_members[:expansion_limit]
    )


def _full_expansion_limit_for_combo_counts(
    combo_counts: dict[str, int],
    merged_combo_catalog: _MergedComboCatalog,
) -> int:
    """Upper bound on label variants for one structural hit (product of group sizes)."""
    limit = 1
    for merged_combo_id, count in combo_counts.items():
        if count <= 0:
            continue
        members = merged_combo_catalog.members_by_merged_id[merged_combo_id]
        if is_generic_zero_military_score_combo_id(merged_combo_id) or count != 1:
            continue
        limit *= max(1, len(members))
    return max(1, limit)


def _expand_score_equivalent_solutions(
    problem: InferenceProblem,
    action_counts: dict[str, int],
    combo_counts: dict[str, int],
    merged_combo_catalog: _MergedComboCatalog,
    *,
    max_expansions: int,
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
        _ship_build_variants_for_merged_count(
            merged_combo_id,
            count,
            merged_combo_catalog,
            max_expansions=max_expansions,
        )
        for merged_combo_id, count in combo_counts.items()
        if count > 0
    ]
    if not ship_build_variant_lists and not solution_actions:
        return []
    # Action-only hits have no ship-build axes; synthesize one empty combination.
    ship_build_combinations: list[tuple[InferenceSolutionShipBuild, ...]]
    if not ship_build_variant_lists:
        ship_build_combinations = [()]
    else:
        ship_build_combinations = [
            tuple(ship_build_variant) for ship_build_variant in product(*ship_build_variant_lists)
        ]
    solutions: list[InferenceSolution] = []
    for ship_builds in ship_build_combinations:
        solutions.append(
            InferenceSolution(
                objective_value=_objective_value(problem, action_counts, ship_builds),
                actions=tuple(solution_actions),
                ship_builds=ship_builds,
            )
        )
    solutions.sort(key=lambda solution: solution.objective_value, reverse=True)
    return solutions[: max(1, max_expansions)]


def _insert_solution_by_objective(
    output: list[InferenceSolution],
    solution: InferenceSolution,
) -> None:
    """Insert ``solution`` into ``output`` keeping objective descending order.

    Equal objectives append after existing ties so expansion encounter order
    (probability then combo id) is preserved.
    """
    objectives = [-held.objective_value for held in output]
    index = bisect_right(objectives, -solution.objective_value)
    output.insert(index, solution)


def expand_structural_hits_to_top_k(
    problem: InferenceProblem,
    structural_hits: Sequence[tuple[dict[str, int], dict[str, int]]],
    merged_combo_catalog: _MergedComboCatalog,
    *,
    max_solutions: int,
) -> list[InferenceSolution]:
    """Expand distinct CP-SAT hits into label variants; keep a streaming top-K.

    Solve-loop budget is structural (merged signatures). Label variants of the same
    military arithmetic are expanded here and culled so at most ``max_solutions``
    rows are retained, ranked by objective.
    """
    if max_solutions <= 0 or not structural_hits:
        return []

    ranked_hits: list[tuple[int, dict[str, int], dict[str, int]]] = []
    for action_counts, combo_counts in structural_hits:
        best_only = _expand_score_equivalent_solutions(
            problem,
            action_counts,
            combo_counts,
            merged_combo_catalog,
            max_expansions=1,
        )
        if not best_only:
            continue
        ranked_hits.append((best_only[0].objective_value, action_counts, combo_counts))
    ranked_hits.sort(key=lambda item: item[0], reverse=True)

    output: list[InferenceSolution] = []
    seen_signatures: set[tuple[tuple[str, int], ...]] = set()
    kth_objective: int | None = None
    for best_objective, action_counts, combo_counts in ranked_hits:
        if (
            kth_objective is not None
            and len(output) >= max_solutions
            and best_objective <= kth_objective
        ):
            break
        expansions = _expand_score_equivalent_solutions(
            problem,
            action_counts,
            combo_counts,
            merged_combo_catalog,
            max_expansions=_full_expansion_limit_for_combo_counts(
                combo_counts,
                merged_combo_catalog,
            ),
        )
        for expansion in expansions:
            if kth_objective is not None and expansion.objective_value <= kth_objective:
                # Expansions are objective-descending; remaining cannot enter.
                break
            signature = solution_signature(expansion)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            _insert_solution_by_objective(output, expansion)
            if len(output) > max_solutions:
                evicted = output.pop()
                seen_signatures.discard(solution_signature(evicted))
            if len(output) >= max_solutions:
                kth_objective = output[max_solutions - 1].objective_value
    return output


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

    if problem.race_id is not None and is_horwasp(problem.race_id):
        return InferenceResult(
            status=STATUS_NO_EXACT_SOLUTION,
            solutions=(),
            diagnostics={"reason": "horwasp_unsupported"},
        )

    if not _problem_has_catalog_entries(problem):
        if _observation_is_solver_idle(problem):
            idle_solution = InferenceSolution(objective_value=0, actions=())
            if on_solution is not None:
                on_solution(idle_solution)
            return InferenceResult(
                status=STATUS_EXACT,
                solutions=(idle_solution,),
                diagnostics={"solver_status": "NO_ACTIONS", "solution_count": 1},
            )
        return InferenceResult(
            status=STATUS_NO_EXACT_SOLUTION,
            solutions=(),
            diagnostics={"reason": "no candidate actions for non-zero observation deltas"},
        )

    freighter_only_solution = _freighter_only_zero_military_solution(problem)
    if freighter_only_solution is not None:
        if on_solution is not None:
            on_solution(freighter_only_solution)
        return InferenceResult(
            status=STATUS_EXACT,
            solutions=(freighter_only_solution,),
            diagnostics={
                "solver_status": "FREIGHTER_ONLY_FAST_PATH",
                "solution_count": 1,
                "stopped_reason": "freighter_only_fast_path",
            },
        )

    merged_combo_catalog = _merge_score_equivalent_combos(problem.ship_build_combos)
    built_model = _build_model(problem, merged_combo_catalog)
    build_diagnostics = _solver_build_diagnostics(problem, built_model)
    model = built_model.model
    action_count_vars = built_model.action_count_vars
    combo_count_vars = built_model.combo_count_vars
    objective_var = built_model.objective_var
    solver = cp_model.CpSolver()
    structural_hits: list[tuple[dict[str, int], dict[str, int]]] = []
    started_at = time.monotonic()
    last_solver_status = cp_model.UNKNOWN
    stopped_reason = "exhausted"
    time_limited = False
    top_solution_bucket_counts: dict[str, tuple[int, ...]] = {}
    near_best_threshold = problem.near_best_objective_threshold
    tier_max_objective: int | None = None
    max_objective: int | None = None
    near_best_band_applied = False

    while len(structural_hits) < problem.max_solutions:
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
            if last_solver_status == cp_model.UNKNOWN and structural_hits:
                time_limited = True
                stopped_reason = "time_budget"
            elif near_best_band_applied and structural_hits:
                stopped_reason = "near_best_band_exhausted"
            elif not structural_hits:
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
        ranking_bin_indicators = _ranking_bin_indicators_by_action_id(problem, action_counts)
        structural_hits.append((action_counts, combo_counts))
        top_solution_bucket_counts = ranking_bin_indicators

        found_objective = int(solver.ObjectiveValue())
        if tier_max_objective is None:
            tier_max_objective = found_objective
            max_objective = found_objective
            if near_best_threshold is not None:
                model.add(objective_var >= tier_max_objective - near_best_threshold)
                near_best_band_applied = True
        else:
            max_objective = found_objective

        if near_best_band_applied and max_objective is not None:
            # Sliding ceiling: next maximize walks next-best inside [Z*-T, max].
            model.add(objective_var <= max_objective)

        _add_no_good_cut(
            model,
            action_count_vars,
            combo_count_vars,
            action_counts,
            combo_counts,
            len(structural_hits),
        )

        if len(structural_hits) >= problem.max_solutions:
            stopped_reason = "max_solutions"
            break

    solutions = expand_structural_hits_to_top_k(
        problem,
        structural_hits,
        merged_combo_catalog,
        max_solutions=problem.max_solutions,
    )
    if on_solution is not None:
        for solution in solutions:
            on_solution(solution)

    diagnostics: dict[str, object] = {
        **build_diagnostics,
        "solver_status": solver.status_name(last_solver_status),
        "solution_count": len(solutions),
        "structural_hit_count": len(structural_hits),
        "stopped_reason": stopped_reason,
        "wall_time_seconds": time.monotonic() - started_at,
        "policy_step_id": problem.policy_step_id,
        "policy_step_index": problem.policy_step_index,
        "military_score_alpha": problem.military_score_alpha,
    }
    if near_best_threshold is not None:
        diagnostics["nearBestObjectiveThreshold"] = near_best_threshold
    if tier_max_objective is not None:
        diagnostics["tierMaxObjective"] = tier_max_objective
    if time_limited:
        diagnostics["time_limited"] = True
    if top_solution_bucket_counts:
        diagnostics["rankingBinIndicatorsByActionId"] = top_solution_bucket_counts

    if solutions:
        solutions.sort(key=lambda solution: solution.objective_value, reverse=True)

    if stopped_reason == "cancelled":
        status = STATUS_STOPPED
    elif not solutions:
        status = STATUS_TIME_LIMITED if time_limited else STATUS_NO_EXACT_SOLUTION
    else:
        status = STATUS_TIME_LIMITED if time_limited else STATUS_EXACT

    return InferenceResult(status=status, solutions=tuple(solutions), diagnostics=diagnostics)
