"""Near-best structural search: objective banding and held seed no-goods.

Owns the CP-SAT search that collects distinct merged signatures within the
near-best objective band, plus no-good cuts for prior-tier held solutions so
search discovers new structures instead of rediscovering held ones.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.models import (
    InferenceProblem,
    InferenceSolution,
    ShipBuildCombo,
    SolveClip,
    effective_solve_clip,
)
from api.compute.sat_gil_overlap import invoke_cp_sat_solve

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
    near_best_threshold: int
    seed_no_goods_applied: int
    seed_no_goods_skipped: int
    top_solution_bucket_counts: dict[str, tuple[int, ...]]
    hang_fuse_hit: bool = False
    deterministic_time: float = 0.0
    # Sum of ``invoke_cp_sat_solve`` wall only -- hang-fuse / row charge clock.
    solve_wall_seconds: float = 0.0


def configured_sat_search_workers() -> int:
    """Return CP-SAT ``num_workers`` for one ``Solve()`` call.

    Default is **1**: multi-worker CP-SAT portfolios (LNS) routinely overshoot
    short stream tier search-effort budgets. Parallelism for cold
    ensure / streams belongs on the orchestrator thread pool across per-player
    DAG nodes, not inside one solve. Override with
    ``MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS`` for experiments / batch jobs.

    Callers must set only ``parameters.num_workers``. Also setting the deprecated
    ``num_search_workers`` to a non-zero value makes OR-Tools return
    ``MODEL_INVALID``.
    """
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS")
    if raw is not None:
        return max(1, int(raw))
    return 1


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


def member_combo_id_to_merged_id(
    merged_combo_catalog: SupportsMergedComboCatalog,
) -> dict[str, str]:
    """Map each member combo id, and each merged id, to its merged variable id."""
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
    member_to_merged: dict[str, str] | None = None,
) -> tuple[dict[str, int], dict[str, int]] | None:
    """Map a held (possibly labeled) solution onto current CP-SAT count vars.

    Returns full action/combo count vectors including zeros, or ``None`` when the
    solution cannot be expressed in this catalog (unknown combo or aggregate).
    ``member_to_merged`` is the catalog map; pass one built for the whole held set.
    """
    if member_to_merged is None:
        member_to_merged = member_combo_id_to_merged_id(merged_combo_catalog)
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
    member_to_merged = member_combo_id_to_merged_id(merged_combo_catalog)
    for seed in seed_solutions:
        mapped = merged_assignment_from_solution(
            seed,
            problem=problem,
            merged_combo_catalog=merged_combo_catalog,
            member_to_merged=member_to_merged,
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


# Actions, then combos. Each side is the positive ``(id, count)`` pairs in model order.
SparseAssignmentKey = tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]


def sparse_assignment_key(
    action_counts_in_model_order: Iterable[tuple[str, int]],
    combo_counts_in_model_order: Iterable[tuple[str, int]],
) -> SparseAssignmentKey:
    """Seen-set identity of one assignment, with zero counts omitted.

    Both sequences must list every variable exactly once, in model order:
    ``problem.aggregate_actions`` for actions and ``merged_combo_catalog.combos``
    for combos. Those are the orders of ``action_count_vars`` and
    ``combo_count_vars``. Building the scan list once from those dicts, and
    reading every entry, keeps this key equal to a dense ``(id, count)`` tuple
    that includes the zeros.

    A count of zero is omitted. An id left out of a sequence is stored the same
    way as a zero, so two assignments that differ only on a skipped id share a
    key.
    """
    return (
        tuple((name, count) for name, count in action_counts_in_model_order if count != 0),
        tuple((name, count) for name, count in combo_counts_in_model_order if count != 0),
    )


class _ObjectiveBandCollector(cp_model.CpSolverSolutionCallback):
    """Keep the best ``hit_cap`` assignments seen while enumerating the band.

    Proto indexes are snapshotted from ``action_count_vars`` and
    ``combo_count_vars`` at construction, in ``problem.aggregate_actions`` order
    and ``merged_combo_catalog.combos`` order. Each callback reads every
    snapshotted index via ``SolutionIntegerValue`` and dedups with
    ``sparse_assignment_key``.
    """

    def __init__(
        self,
        problem: InferenceProblem,
        merged_combo_catalog: SupportsMergedComboCatalog,
        action_count_vars: dict[str, cp_model.IntVar],
        combo_count_vars: dict[str, cp_model.IntVar],
        objective_var: cp_model.IntVar,
        *,
        first_objective: int,
        first_hit: tuple[dict[str, int], dict[str, int]],
        hit_cap: int,
        cancel_token: InferenceCancelToken | None,
    ) -> None:
        super().__init__()
        self._action_reads = tuple(
            (action.id, action_count_vars[action.id].index) for action in problem.aggregate_actions
        )
        self._combo_reads = tuple(
            (combo.combo_id, combo_count_vars[combo.combo_id].index)
            for combo in merged_combo_catalog.combos
        )
        self._objective_index = objective_var.index
        self._hit_cap = hit_cap
        self._cancel_token = cancel_token
        self.cancelled = False
        self.found = 1
        action_counts, combo_counts = first_hit
        self._seen = {
            sparse_assignment_key(
                ((name, action_counts[name]) for name, _index in self._action_reads),
                ((name, combo_counts[name]) for name, _index in self._combo_reads),
            )
        }
        self.best: list[tuple[int, dict[str, int], dict[str, int]]] = [
            (first_objective, action_counts, combo_counts)
        ]

    def _read_counts(self, reads: tuple[tuple[str, int], ...]) -> Iterable[tuple[str, int]]:
        for name, index in reads:
            yield name, int(self.SolutionIntegerValue(index))

    def on_solution_callback(self) -> None:
        if self._cancel_token is not None and self._cancel_token.is_cancelled():
            self.cancelled = True
            self.StopSearch()
            return
        key = sparse_assignment_key(
            self._read_counts(self._action_reads),
            self._read_counts(self._combo_reads),
        )
        if key in self._seen:
            return
        self._seen.add(key)
        self.found += 1
        objective = int(self.SolutionIntegerValue(self._objective_index))
        if len(self.best) >= self._hit_cap and objective <= self.best[-1][0]:
            return
        action_pairs, combo_pairs = key
        self.best.append((objective, dict(action_pairs), dict(combo_pairs)))
        self.best.sort(key=lambda item: item[0], reverse=True)
        if len(self.best) > self._hit_cap:
            self.best.pop()


def _solver_effort(solver: cp_model.CpSolver) -> float:
    try:
        return max(0.0, float(solver.deterministic_time))
    except RuntimeError, TypeError, ValueError:
        return 0.0


def _enumerate_objective_band(
    problem: InferenceProblem,
    *,
    model: cp_model.CpModel,
    action_count_vars: dict[str, cp_model.IntVar],
    combo_count_vars: dict[str, cp_model.IntVar],
    objective_var: cp_model.IntVar,
    merged_combo_catalog: SupportsMergedComboCatalog,
    base_clip: SolveClip,
    started_at: float,
    effort_spent: float,
    solve_wall_seconds: float,
    first_objective: int,
    first_hit: tuple[dict[str, int], dict[str, int]],
    hit_cap: int,
    cancel_token: InferenceCancelToken | None,
    last_solver_status: int,
) -> tuple[
    list[tuple[dict[str, int], dict[str, int]]],
    str,
    bool,
    bool,
    int,
    float,
    float,
    dict[str, tuple[int, ...]],
]:
    """Enumerate ``[Z*-T, Z*]`` once and keep the best ``hit_cap`` signatures.

    The caller has already maximized once and posted the band plus a no-good for
    that first assignment. Clearing the objective makes the follow-up a
    satisfiability enumeration of the remaining band.
    """
    advance = base_clip.next_solve(
        effort_spent=effort_spent,
        elapsed_seconds=time.monotonic() - started_at,
        solve_wall_seconds=solve_wall_seconds,
    )
    first_only = [first_hit]
    first_bins = _ranking_bin_indicators_by_action_id(problem, first_hit[0])
    if advance.clip is None or advance.hang_fuse:
        return (
            [] if advance.hang_fuse else first_only,
            "hang_fuse" if advance.hang_fuse else "time_budget",
            False if advance.hang_fuse else True,
            bool(advance.hang_fuse),
            last_solver_status,
            effort_spent,
            solve_wall_seconds,
            {} if advance.hang_fuse else first_bins,
        )

    model.clear_objective()
    collector = _ObjectiveBandCollector(
        problem,
        merged_combo_catalog,
        action_count_vars,
        combo_count_vars,
        objective_var,
        first_objective=first_objective,
        first_hit=first_hit,
        hit_cap=hit_cap,
        cancel_token=cancel_token,
    )
    solver = cp_model.CpSolver()
    advance.clip.apply_to_solver(solver)
    solver.parameters.num_workers = configured_sat_search_workers()
    solver.parameters.enumerate_all_solutions = True
    wall_before = time.monotonic()
    status = invoke_cp_sat_solve(solver, model, collector)
    wall_delta = time.monotonic() - wall_before
    effort_spent += _solver_effort(solver)
    solve_wall_seconds += wall_delta
    hits = [(actions, combos) for _objective, actions, combos in collector.best]
    best_bins = _ranking_bin_indicators_by_action_id(problem, hits[0][0]) if hits else {}

    if collector.cancelled or (cancel_token is not None and cancel_token.is_cancelled()):
        return (
            hits,
            "cancelled",
            False,
            False,
            status,
            effort_spent,
            solve_wall_seconds,
            best_bins,
        )

    decision = base_clip.after_solve(
        solver_status=status,
        effort_spent=effort_spent,
        solve_wall_seconds=solve_wall_seconds,
        elapsed_seconds=time.monotonic() - started_at,
        has_structural_hits=bool(hits),
    )
    if decision.hang_fuse:
        return (
            [],
            "hang_fuse",
            False,
            True,
            status,
            effort_spent,
            solve_wall_seconds,
            {},
        )
    # OPTIMAL/INFEASIBLE means the band was fully enumerated. A clip that also
    # happens to be numerically spent does not discard that completed set.
    if status not in (cp_model.OPTIMAL, cp_model.INFEASIBLE):
        return (
            hits,
            "time_budget",
            True,
            False,
            status,
            effort_spent,
            solve_wall_seconds,
            best_bins,
        )
    stopped = "max_solutions" if collector.found > hit_cap else "near_best_band_exhausted"
    return (
        hits,
        stopped,
        False,
        False,
        status,
        effort_spent,
        solve_wall_seconds,
        best_bins,
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
    structural_hit_limit: int | None = None,
    successive_search: bool = False,
) -> NearBestStructuralSearchOutcome:
    """Collect distinct merged signatures within the near-best objective band.

    One maximization learns the best ranking ``Z*``. When more than one hit is
    wanted, the rest of the band ``[Z*-T, Z*]`` is enumerated in that same model
    instead of re-solving once per hit. ``structural_hit_limit`` stops after that
    many hits (seed passes pass 1). ``successive_search`` keeps the per-hit
    re-solve walk so tests can compare it with the band enumeration.
    """
    if seed_no_good_solutions:
        seed_no_goods_applied, seed_no_goods_skipped = seed_no_good_cuts_for_held_solutions(
            model,
            problem=problem,
            merged_combo_catalog=merged_combo_catalog,
            action_count_vars=action_count_vars,
            combo_count_vars=combo_count_vars,
            seed_solutions=seed_no_good_solutions,
        )
    else:
        seed_no_goods_applied, seed_no_goods_skipped = 0, 0
    solver = cp_model.CpSolver()
    structural_hits: list[tuple[dict[str, int], dict[str, int]]] = []
    started_at = time.monotonic()
    last_solver_status = cp_model.UNKNOWN
    stopped_reason = "exhausted"
    time_limited = False
    hang_fuse_hit = False
    base_clip = effective_solve_clip(
        solve_clip=problem.solve_clip,
        time_limit_seconds=problem.time_limit_seconds,
    )
    effort_spent = 0.0
    solve_wall_seconds = 0.0
    top_solution_bucket_counts: dict[str, tuple[int, ...]] = {}
    near_best_threshold = problem.near_best_objective_threshold
    tier_max_objective: int | None = None
    max_objective: int | None = None
    near_best_band_applied = False
    # Seed passes ask for one hit. A completed free search enumerates the band
    # after that first maximization instead of restarting once per hit.
    enumerate_band = (
        structural_hit_limit is None and not successive_search and problem.max_solutions > 1
    )
    if structural_hit_limit is None:
        search_cap = 1 if enumerate_band else problem.max_solutions
    else:
        search_cap = min(problem.max_solutions, structural_hit_limit)
    final_hit_cap = problem.max_solutions if enumerate_band else search_cap

    while len(structural_hits) < search_cap:
        if cancel_token is not None and cancel_token.is_cancelled():
            stopped_reason = "cancelled"
            break

        advance = base_clip.next_solve(
            effort_spent=effort_spent,
            elapsed_seconds=time.monotonic() - started_at,
            solve_wall_seconds=solve_wall_seconds,
        )
        if advance.clip is None:
            if advance.hang_fuse:
                hang_fuse_hit = True
                stopped_reason = "hang_fuse"
            else:
                time_limited = True
                stopped_reason = "time_budget"
            break
        advance.clip.apply_to_solver(solver)
        # Set only ``num_workers``. Setting both ``num_workers`` and the deprecated
        # ``num_search_workers`` to non-zero values makes OR-Tools return
        # MODEL_INVALID on this model (empty search; fleet warships stay "?").
        solver.parameters.num_workers = configured_sat_search_workers()
        callback = _StopSearchOnCancel(cancel_token) if cancel_token is not None else None
        wall_before = time.monotonic()
        last_solver_status = invoke_cp_sat_solve(solver, model, callback)
        wall_delta = time.monotonic() - wall_before
        # Each Solve() reports only its own deterministic time.
        try:
            solve_effort = max(0.0, float(solver.deterministic_time))
        except RuntimeError:
            solve_effort = 0.0
        effort_spent += solve_effort
        solve_wall_seconds += wall_delta

        if cancel_token is not None and cancel_token.is_cancelled():
            stopped_reason = "cancelled"
            break
        decision = base_clip.after_solve(
            solver_status=last_solver_status,
            effort_spent=effort_spent,
            solve_wall_seconds=solve_wall_seconds,
            elapsed_seconds=time.monotonic() - started_at,
            has_structural_hits=bool(structural_hits),
        )
        if decision.hang_fuse:
            hang_fuse_hit = True
            time_limited = False
            stopped_reason = "hang_fuse"
            break
        if decision.time_limited:
            time_limited = True
            stopped_reason = "time_budget"

        if last_solver_status not in _SUCCESS_STATUSES:
            if time_limited:
                stopped_reason = "time_budget"
            elif near_best_band_applied and structural_hits:
                stopped_reason = "near_best_band_exhausted"
            else:
                stopped_reason = "infeasible"
            break

        action_counts = _read_action_counts(problem, action_count_vars, solver)
        combo_counts = _read_combo_counts(merged_combo_catalog, combo_count_vars, solver)
        ranking_bin_indicators = _ranking_bin_indicators_by_action_id(problem, action_counts)
        structural_hits.append((action_counts, combo_counts))
        top_solution_bucket_counts = ranking_bin_indicators

        found_objective = int(solver.ObjectiveValue())
        if tier_max_objective is None:
            tier_max_objective = found_objective
            max_objective = found_objective
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

        if len(structural_hits) >= search_cap:
            stopped_reason = "max_solutions"
            break

    if (
        enumerate_band
        and structural_hits
        and tier_max_objective is not None
        and not hang_fuse_hit
        and stopped_reason != "cancelled"
        and not time_limited
    ):
        (
            structural_hits,
            stopped_reason,
            time_limited,
            hang_fuse_hit,
            last_solver_status,
            effort_spent,
            solve_wall_seconds,
            top_solution_bucket_counts,
        ) = _enumerate_objective_band(
            problem,
            model=model,
            action_count_vars=action_count_vars,
            combo_count_vars=combo_count_vars,
            objective_var=objective_var,
            merged_combo_catalog=merged_combo_catalog,
            base_clip=base_clip,
            started_at=started_at,
            effort_spent=effort_spent,
            solve_wall_seconds=solve_wall_seconds,
            first_objective=tier_max_objective,
            first_hit=structural_hits[0],
            hit_cap=final_hit_cap,
            cancel_token=cancel_token,
            last_solver_status=last_solver_status,
        )

    if hang_fuse_hit:
        # Fuse fails closed: earlier hits in this search must not be admitted.
        structural_hits = []
        top_solution_bucket_counts = {}
        time_limited = False
        stopped_reason = "hang_fuse"

    return NearBestStructuralSearchOutcome(
        structural_hits=structural_hits,
        last_solver_status=last_solver_status,
        stopped_reason=stopped_reason,
        time_limited=time_limited,
        hang_fuse_hit=hang_fuse_hit,
        deterministic_time=effort_spent,
        solve_wall_seconds=solve_wall_seconds,
        tier_max_objective=tier_max_objective,
        near_best_threshold=near_best_threshold,
        seed_no_goods_applied=seed_no_goods_applied,
        seed_no_goods_skipped=seed_no_goods_skipped,
        top_solution_bucket_counts=top_solution_bucket_counts,
    )
