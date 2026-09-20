"""Near-best structural search: seed no-goods and ranking-bin mapping.

Prepares flattened CP-SAT count variables, runs the catalog-free SAT search
session kernel, then splits assignments into action/combo counts and ranking
bin indicators. Prior-tier held solutions are seeded as no-goods so search
discovers new structures instead of rediscovering held ones.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeVar

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceSolution,
    ShipBuildCombo,
)
from api.compute.sat_session import (
    add_assignment_no_good,
    collect_sat_search_assignments,
)

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken

_CountValue = TypeVar("_CountValue")


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
    near_best_threshold: int
    seed_no_goods_applied: int
    seed_no_goods_skipped: int
    top_solution_bucket_counts: dict[str, tuple[int, ...]]


def _flatten_named_maps(
    action_map: Mapping[str, _CountValue],
    combo_map: Mapping[str, _CountValue],
) -> dict[str, _CountValue]:
    overlap = sorted(set(action_map) & set(combo_map))
    if overlap:
        raise ValueError(f"action and combo count names collide: {overlap!r}")
    return {**action_map, **combo_map}


def add_no_good_cut(
    model: cp_model.CpModel,
    action_count_vars: dict[str, cp_model.IntVar],
    combo_count_vars: dict[str, cp_model.IntVar],
    action_counts: dict[str, int],
    combo_counts: dict[str, int],
    cut_index: int,
) -> None:
    count_vars = _flatten_named_maps(action_count_vars, combo_count_vars)
    assignment = _flatten_named_maps(action_counts, combo_counts)
    add_assignment_no_good(model, count_vars, assignment, cut_index)


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


def _split_assignment(
    assignment: Mapping[str, int],
    *,
    action_ids: Sequence[str],
    combo_ids: Sequence[str],
) -> tuple[dict[str, int], dict[str, int]]:
    return (
        {name: assignment[name] for name in action_ids},
        {name: assignment[name] for name in combo_ids},
    )


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

    Seeds prior-tier held solutions as no-goods, flattens action and combo count
    vars, then runs the SAT-session kernel until the budget, cancel,
    infeasibility, or band exhaustion stops search.
    """
    seed_no_goods_applied, seed_no_goods_skipped = seed_no_good_cuts_for_held_solutions(
        model,
        problem=problem,
        merged_combo_catalog=merged_combo_catalog,
        action_count_vars=action_count_vars,
        combo_count_vars=combo_count_vars,
        seed_solutions=seed_no_good_solutions,
    )
    count_vars = _flatten_named_maps(action_count_vars, combo_count_vars)
    action_ids = tuple(action_count_vars)
    combo_ids = tuple(combo_count_vars)
    collected = collect_sat_search_assignments(
        model,
        count_vars=count_vars,
        names=tuple(count_vars),
        objective_var=objective_var,
        max_solutions=problem.max_solutions,
        time_limit_seconds=problem.time_limit_seconds,
        near_best_threshold=problem.near_best_objective_threshold,
        cancel_event=cancel_token,
    )
    structural_hits = [
        _split_assignment(assignment, action_ids=action_ids, combo_ids=combo_ids)
        for assignment in collected.assignments
    ]
    top_solution_bucket_counts: dict[str, tuple[int, ...]] = {}
    if structural_hits:
        top_solution_bucket_counts = _ranking_bin_indicators_by_action_id(
            problem, structural_hits[-1][0]
        )
    return NearBestStructuralSearchOutcome(
        structural_hits=structural_hits,
        last_solver_status=collected.last_solver_status,
        stopped_reason=collected.stopped_reason,
        time_limited=collected.time_limited,
        tier_max_objective=collected.tier_max_objective,
        near_best_threshold=problem.near_best_objective_threshold,
        seed_no_goods_applied=seed_no_goods_applied,
        seed_no_goods_skipped=seed_no_goods_skipped,
        top_solution_bucket_counts=top_solution_bucket_counts,
    )
