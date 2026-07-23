"""Near-best structural search: objective banding and held seed no-goods.

Owns the CP-SAT iteration that collects distinct merged signatures within the
near-best objective band, plus no-good cuts for prior-tier held solutions so
search discovers new structures instead of rediscovering held ones.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceSolution,
    ShipBuildCombo,
)

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken

_SUCCESS_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)


class SupportsMergedComboCatalog(Protocol):
    """Merged score-equivalent combo view used by CP-SAT count variables."""

    combos: tuple[ShipBuildCombo, ...]
    members_by_merged_id: dict[str, tuple[ShipBuildCombo, ...]]


@dataclass(frozen=True)
class NearBestStructuralSearchOutcome:
    """Result of one near-best structural collection pass."""

    structural_hits: list[tuple[dict[str, int], dict[str, int]]]
    last_solver_status: int
    stopped_reason: str
    time_limited: bool
    tier_max_objective: int | None
    near_best_threshold: int | None
    seed_no_goods_applied: int
    seed_no_goods_skipped: int
    top_solution_bucket_counts: dict[str, tuple[int, ...]]


def _configured_num_search_workers(combo_count: int) -> int | None:
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS")
    if raw is not None:
        return int(raw)
    if combo_count > 100:
        return 8
    return None


def add_no_good_cut(
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


def _member_combo_id_to_merged_id(
    merged_combo_catalog: SupportsMergedComboCatalog,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for merged_id, members in merged_combo_catalog.members_by_merged_id.items():
        mapping[merged_id] = merged_id
        for member in members:
            mapping[member.combo_id] = merged_id
    return mapping


def merged_assignment_from_solution(
    solution: InferenceSolution,
    *,
    problem: InferenceProblem,
    merged_combo_catalog: SupportsMergedComboCatalog,
) -> tuple[dict[str, int], dict[str, int]] | None:
    """Map a held (possibly labeled) solution onto current CP-SAT count vars.

    Returns full action/combo count vectors including zeros, or ``None`` when the
    solution cannot be expressed in this catalog (unknown combo or aggregate).
    """
    member_to_merged = _member_combo_id_to_merged_id(merged_combo_catalog)
    action_ids = {action.id for action in problem.aggregate_actions}
    action_counts = {action.id: 0 for action in problem.aggregate_actions}
    for action in solution.actions:
        if action.count == 0:
            continue
        if action.action_id not in action_ids:
            return None
        action_counts[action.action_id] = action.count

    combo_counts = {combo.combo_id: 0 for combo in merged_combo_catalog.combos}
    for ship_build in solution.ship_builds:
        if ship_build.count == 0:
            continue
        merged_id = member_to_merged.get(ship_build.combo_id)
        if merged_id is None or merged_id not in combo_counts:
            return None
        combo_counts[merged_id] += ship_build.count
    return action_counts, combo_counts


def seed_no_good_cuts_for_held_solutions(
    model: cp_model.CpModel,
    *,
    problem: InferenceProblem,
    merged_combo_catalog: SupportsMergedComboCatalog,
    action_count_vars: dict[str, cp_model.IntVar],
    combo_count_vars: dict[str, cp_model.IntVar],
    seed_solutions: Sequence[InferenceSolution],
) -> tuple[int, int]:
    """Add no-goods for prior-tier held solutions. Returns (applied, skipped)."""
    applied = 0
    skipped = 0
    seen_assignments: set[tuple[tuple[str, int], ...]] = set()
    for seed in seed_solutions:
        mapped = merged_assignment_from_solution(
            seed,
            problem=problem,
            merged_combo_catalog=merged_combo_catalog,
        )
        if mapped is None:
            skipped += 1
            continue
        action_counts, combo_counts = mapped
        assignment_key = tuple(sorted(action_counts.items()) + sorted(combo_counts.items()))
        if assignment_key in seen_assignments:
            continue
        seen_assignments.add(assignment_key)
        add_no_good_cut(
            model,
            action_count_vars,
            combo_count_vars,
            action_counts,
            combo_counts,
            cut_index=-(applied + 1),
        )
        applied += 1
    return applied, skipped


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
    merged_combo_catalog: SupportsMergedComboCatalog,
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


class _StopSearchOnCancel(cp_model.CpSolverSolutionCallback):
    def __init__(self, cancel_token: InferenceCancelToken) -> None:
        super().__init__()
        self._cancel_token = cancel_token

    def on_solution_callback(self) -> None:
        if self._cancel_token.is_cancelled():
            self.StopSearch()


def collect_near_best_structural_hits(
    problem: InferenceProblem,
    *,
    model: cp_model.CpModel,
    action_count_vars: dict[str, cp_model.IntVar],
    combo_count_vars: dict[str, cp_model.IntVar],
    objective_var: cp_model.IntVar,
    merged_combo_catalog: SupportsMergedComboCatalog,
    seed_no_good_solutions: Sequence[InferenceSolution] = (),
    cancel_token: InferenceCancelToken | None = None,
) -> NearBestStructuralSearchOutcome:
    """Collect distinct merged signatures within the near-best objective band.

    Seeds prior-tier held solutions as no-goods, then iteratively maximizes under
    no-good cuts and optional ``[Z*-T, current_max]`` banding until the budget,
    cancel, infeasibility, or band exhaustion stops search.
    """
    seed_no_goods_applied, seed_no_goods_skipped = seed_no_good_cuts_for_held_solutions(
        model,
        problem=problem,
        merged_combo_catalog=merged_combo_catalog,
        action_count_vars=action_count_vars,
        combo_count_vars=combo_count_vars,
        seed_solutions=seed_no_good_solutions,
    )
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

        add_no_good_cut(
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

    return NearBestStructuralSearchOutcome(
        structural_hits=structural_hits,
        last_solver_status=last_solver_status,
        stopped_reason=stopped_reason,
        time_limited=time_limited,
        tier_max_objective=tier_max_objective,
        near_best_threshold=near_best_threshold,
        seed_no_goods_applied=seed_no_goods_applied,
        seed_no_goods_skipped=seed_no_goods_skipped,
        top_solution_bucket_counts=top_solution_bucket_counts,
    )
