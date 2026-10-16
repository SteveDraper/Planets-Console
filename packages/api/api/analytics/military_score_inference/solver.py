"""OR-Tools CP-SAT adapter for military score build inference."""

import heapq
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken

from api.analytics.military_score_inference import catalog_model
from api.analytics.military_score_inference.catalog_model import BuiltModel, MergedComboCatalog
from api.analytics.military_score_inference.inference_objective import max_combo_probability_weight
from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.near_best_structural_search import (
    collect_near_best_structural_hits,
    merged_assignment_from_solution,  # noqa: F401 -- re-export for stable solver import path
)
from api.analytics.military_score_inference.ranked_solution_buffer import (
    admit_ranked_solution,
    solution_signature,  # noqa: F401 -- re-export for stable solver import path
)
from api.analytics.military_score_inference.ranking_heuristics import (
    InferenceRankingHeuristics,
    compute_bin_penalty_objective_contribution,
    compute_overflow_objective_contribution,
    ranking_heuristics_diagnostics_payload,
    ship_build_objective_coefficient,
)
from api.analytics.military_score_inference.ship_build_combos import (
    is_generic_zero_military_score_combo_id,
)
from api.analytics.military_score_inference.tier_solve_cache import TierSolveCache
from api.concepts.races import is_horwasp

STATUS_EXACT = "exact"
STATUS_INVALID_PROBLEM = "invalid_problem"
STATUS_NO_EXACT_SOLUTION = "no_exact_solution"
STATUS_MODERATE_RESIDUAL = "moderate_residual"
STATUS_MINE_SCORE_RESIDUAL = "mine_score_residual"
STATUS_STOPPED = "stopped"
STATUS_TIME_LIMITED = "time_limited"


def _solver_build_diagnostics(
    problem: InferenceProblem,
    built_model: BuiltModel,
) -> dict[str, object]:
    """Diagnostics fixed at CP-SAT model build time; merged into InferenceResult.diagnostics."""
    return {
        "rankingHeuristics": ranking_heuristics_diagnostics_payload(
            problem.ranking_heuristics,
            admission_caps_by_action_id=problem.admission_caps_by_action_id,
        ),
        "diversityCapsApplied": list(built_model.diversity_caps_applied),
        "catalogShipFitCount": built_model.catalog_ship_fits,
        "reachableShipFitCount": built_model.reachable_ship_fits,
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
        coefficient = ship_build_objective_coefficient(
            combo_by_id[ship_build.combo_id],
            max_combo_weight=max_combo_weight,
            heuristics=problem.ranking_heuristics,
        )
        objective_value += coefficient * ship_build.count
    return objective_value


def solution_rank_objective(
    problem: InferenceProblem,
    solution: InferenceSolution,
) -> int:
    """Rank weight for an already-built solution (same terms as the CP-SAT objective)."""
    action_counts = {action.action_id: action.count for action in solution.actions}
    return _objective_value(problem, action_counts, solution.ship_builds)


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


@dataclass(frozen=True, slots=True)
class _RankedFitting:
    """One scored fitting of a merged class."""

    contribution: int
    ship_build: InferenceSolutionShipBuild


@dataclass(frozen=True, slots=True)
class _RankedLabeling:
    """One labeling and the sum of its per-ship contributions."""

    contribution: int
    ship_builds: tuple[InferenceSolutionShipBuild, ...]


def _fittings_for_merged_count(
    merged_combo_id: str,
    count: int,
    merged_combo_catalog: MergedComboCatalog,
    *,
    max_labelings: int,
    max_combo_weight: int,
    heuristics: InferenceRankingHeuristics,
) -> tuple[_RankedFitting, ...]:
    """Fittings of one class, contribution descending then combo id ascending.

    A repeated class (count other than 1) keeps its best fitting. A count of
    1 keeps the first ``max_labelings`` fittings. That prefix is the only one
    a top-K labeling can use: equal-sum labelings emit in ascending
    index-tuple order over axes in ``combo_counts`` order.
    """
    members = merged_combo_catalog.members_by_merged_id[merged_combo_id]
    if is_generic_zero_military_score_combo_id(merged_combo_id):
        member = members[0]
        coefficient = ship_build_objective_coefficient(
            member,
            max_combo_weight=max_combo_weight,
            heuristics=heuristics,
        )
        return (
            _RankedFitting(
                contribution=coefficient * count,
                ship_build=_ship_build_from_member(member, count),
            ),
        )

    fittings = [
        _RankedFitting(
            contribution=ship_build_objective_coefficient(
                member,
                max_combo_weight=max_combo_weight,
                heuristics=heuristics,
            )
            * count,
            ship_build=_ship_build_from_member(member, count),
        )
        for member in members
    ]
    keep_count = 1 if count != 1 else max_labelings
    return tuple(
        heapq.nsmallest(
            keep_count,
            fittings,
            key=lambda fitting: (-fitting.contribution, fitting.ship_build.combo_id),
        )
    )


def _best_label_combinations(
    axes: Sequence[Sequence[_RankedFitting]],
    *,
    max_labelings: int,
) -> list[_RankedLabeling]:
    """Top ``max_labelings`` labelings by summed per-ship contribution.

    Axes are in ``combo_counts`` order, each ordered by contribution
    descending then combo id ascending. Equal-sum labelings are emitted in
    ascending index-tuple order. The cartesian product is not materialized.
    """
    if max_labelings <= 0 or not axes:
        return []
    start = tuple(0 for _ in axes)
    start_score = sum(axis[0].contribution for axis in axes)
    # Min-heap of (-score, index tuple). Equal scores pop in ascending index order.
    pending: list[tuple[int, tuple[int, ...]]] = [(-start_score, start)]
    seen = {start}
    labelings: list[_RankedLabeling] = []
    while pending and len(labelings) < max_labelings:
        negative_score, indexes = heapq.heappop(pending)
        parent_score = -negative_score
        labelings.append(
            _RankedLabeling(
                contribution=parent_score,
                ship_builds=tuple(
                    axes[axis_index][member_index].ship_build
                    for axis_index, member_index in enumerate(indexes)
                ),
            )
        )
        for axis_index, axis in enumerate(axes):
            next_member = indexes[axis_index] + 1
            if next_member >= len(axis):
                continue
            neighbor = indexes[:axis_index] + (next_member,) + indexes[axis_index + 1 :]
            if neighbor in seen:
                continue
            seen.add(neighbor)
            neighbor_score = (
                parent_score
                - axis[indexes[axis_index]].contribution
                + axis[next_member].contribution
            )
            heapq.heappush(pending, (-neighbor_score, neighbor))
    return labelings


def _expand_score_equivalent_solutions(
    problem: InferenceProblem,
    action_counts: dict[str, int],
    combo_counts: dict[str, int],
    merged_combo_catalog: MergedComboCatalog,
    *,
    max_labelings: int,
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
                counterparty_player_id=action.counterparty_player_id,
            )
        )
    max_labelings = max(1, max_labelings)
    max_combo_weight = max_combo_probability_weight(problem)
    heuristics = problem.ranking_heuristics
    ship_build_axes = [
        _fittings_for_merged_count(
            merged_combo_id,
            count,
            merged_combo_catalog,
            max_labelings=max_labelings,
            max_combo_weight=max_combo_weight,
            heuristics=heuristics,
        )
        for merged_combo_id, count in combo_counts.items()
        if count > 0
    ]
    action_constant = _objective_value(problem, action_counts, ())
    # Idle exact (all-zero counts) and action-only hits are valid structural hits.
    # Both yield exactly one solution with no ship builds.
    if not ship_build_axes:
        return [
            InferenceSolution(
                objective_value=action_constant,
                actions=tuple(solution_actions),
                ship_builds=(),
            )
        ]
    solutions: list[InferenceSolution] = []
    for labeling in _best_label_combinations(
        ship_build_axes,
        max_labelings=max_labelings,
    ):
        solutions.append(
            InferenceSolution(
                objective_value=action_constant + labeling.contribution,
                actions=tuple(solution_actions),
                ship_builds=labeling.ship_builds,
            )
        )
    return solutions


def expand_structural_hits_to_top_k(
    problem: InferenceProblem,
    structural_hits: Sequence[tuple[dict[str, int], dict[str, int]]],
    merged_combo_catalog: MergedComboCatalog,
    *,
    max_solutions: int,
) -> list[InferenceSolution]:
    """Expand distinct CP-SAT hits into label variants; keep a streaming top-K.

    Solve-loop budget is structural (merged signatures). A hit's objective is the
    sum of one contribution per ship, so each class is ranked on its own and only
    the top ``max_solutions`` labelings of that sum are admitted.
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
            max_labelings=1,
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
            max_labelings=max_solutions,
        )
        for expansion in expansions:
            if kth_objective is not None and expansion.objective_value <= kth_objective:
                # Expansions are objective-descending; remaining cannot enter.
                break
            if not admit_ranked_solution(
                output,
                seen_signatures,
                expansion,
                max_solutions=max_solutions,
            ):
                continue
            if len(output) >= max_solutions:
                kth_objective = output[max_solutions - 1].objective_value
    return output


def solve_inference_problem(
    problem: InferenceProblem,
    *,
    on_solution: Callable[[InferenceSolution], None] | None = None,
    cancel_token: InferenceCancelToken | None = None,
    seed_no_good_solutions: Sequence[InferenceSolution] = (),
    tier_solve_cache: TierSolveCache | None = None,
    fixed_combo_counts: dict[str, int] | None = None,
    combo_count_neighborhood: int = 0,
    structural_hit_limit: int | None = None,
    successive_structural_search: bool = False,
) -> InferenceResult:
    """Return up to max_solutions ranked feasible explanations for one player turn.

    ``seed_no_good_solutions`` are prior-tier held explanations mapped into this
    catalog as no-goods so search finds *new* structures instead of rediscovering
    already-held near-best ship-only (or other) assignments.
    """
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

    prepared_seed_counts: tuple[int, int] | None = None
    if tier_solve_cache is not None:
        built_model, seed_applied, seed_skipped = tier_solve_cache.fresh_model(
            problem,
            fixed_combo_counts,
            combo_count_neighborhood,
            seed_no_good_solutions,
        )
        merged_combo_catalog = built_model.merged_combo_catalog
        search_seeds: Sequence[InferenceSolution] = ()
        prepared_seed_counts = (seed_applied, seed_skipped)
    else:
        merged_combo_catalog = catalog_model.merge_score_equivalent_combos(
            problem.ship_build_combos
        )
        built_model = catalog_model.build_model(problem, merged_combo_catalog)
        merged_combo_catalog = built_model.merged_combo_catalog
        search_seeds = seed_no_good_solutions
    build_diagnostics = _solver_build_diagnostics(problem, built_model)
    started_at = time.monotonic()
    search = collect_near_best_structural_hits(
        problem,
        model=built_model.model,
        action_count_vars=built_model.action_count_vars,
        combo_count_vars=built_model.combo_count_vars,
        objective_var=built_model.objective_var,
        merged_combo_catalog=merged_combo_catalog,
        seed_no_good_solutions=search_seeds,
        cancel_token=cancel_token,
        structural_hit_limit=structural_hit_limit,
        successive_search=successive_structural_search,
    )

    # Hang fuse: drop solutions before admission. Charge path raises after this.
    if search.hang_fuse_hit:
        solutions: list[InferenceSolution] = []
    else:
        solutions = expand_structural_hits_to_top_k(
            problem,
            search.structural_hits,
            merged_combo_catalog,
            max_solutions=problem.max_solutions,
        )
        if on_solution is not None:
            for solution in solutions:
                on_solution(solution)

    diagnostics: dict[str, object] = {
        **build_diagnostics,
        "solver_status": cp_model.CpSolver().status_name(search.last_solver_status),
        "solution_count": len(solutions),
        "structural_hit_count": len(search.structural_hits),
        "stopped_reason": search.stopped_reason,
        "wall_time_seconds": time.monotonic() - started_at,
        "deterministicTime": search.deterministic_time,
        "solveWallSeconds": search.solve_wall_seconds,
        "hangFuseHit": search.hang_fuse_hit,
        "policy_step_id": problem.policy_step_id,
        "policy_step_index": problem.policy_step_index,
        "military_score_alpha": problem.military_score_alpha,
        "military_overshoot_cap_2x": problem.military_overshoot_cap_2x,
    }
    diagnostics["nearBestObjectiveThreshold"] = search.near_best_threshold
    if search.tier_max_objective is not None:
        diagnostics["tierMaxObjective"] = search.tier_max_objective
    if seed_no_good_solutions:
        if prepared_seed_counts is not None:
            diagnostics["seedNoGoodCount"] = prepared_seed_counts[0]
            diagnostics["seedNoGoodSkippedCount"] = prepared_seed_counts[1]
        else:
            diagnostics["seedNoGoodCount"] = search.seed_no_goods_applied
            diagnostics["seedNoGoodSkippedCount"] = search.seed_no_goods_skipped
    if search.hang_fuse_hit:
        diagnostics["hangFuseHit"] = True
    elif search.time_limited:
        diagnostics["time_limited"] = True
    if search.top_solution_bucket_counts:
        diagnostics["rankingBinIndicatorsByActionId"] = search.top_solution_bucket_counts

    if solutions:
        solutions.sort(key=lambda solution: solution.objective_value, reverse=True)

    if search.stopped_reason == "cancelled":
        status = STATUS_STOPPED
    elif search.hang_fuse_hit:
        # Not exact / not time_limited; charge raises InferenceSearchHangFuse next.
        status = STATUS_NO_EXACT_SOLUTION
    elif not solutions:
        status = STATUS_TIME_LIMITED if search.time_limited else STATUS_NO_EXACT_SOLUTION
    else:
        status = STATUS_TIME_LIMITED if search.time_limited else STATUS_EXACT

    return InferenceResult(status=status, solutions=tuple(solutions), diagnostics=diagnostics)
