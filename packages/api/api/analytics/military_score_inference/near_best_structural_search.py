"""Near-best structural search: objective banding and held seed no-goods.

Owns the CP-SAT search that collects distinct merged signatures within the
near-best objective band, plus no-good cuts for prior-tier held solutions so
search discovers new structures instead of rediscovering held ones.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.catalog_model import BuiltModel
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


@dataclass
class StructuralSearchProgress:
    """Hits, stop, and effort shared by maximization and band enumeration."""

    structural_hits: list[tuple[dict[str, int], dict[str, int]]] = field(default_factory=list)
    stopped_reason: str = "exhausted"
    time_limited: bool = False
    hang_fuse_hit: bool = False
    last_solver_status: int = cp_model.UNKNOWN
    effort_spent: float = 0.0
    solve_wall_seconds: float = 0.0
    top_solution_bucket_counts: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def apply_hang_fuse_fail_closed(self) -> None:
        """A hang fuse admits nothing found during this search."""
        if not self.hang_fuse_hit:
            return
        self.structural_hits = []
        self.top_solution_bucket_counts = {}
        self.time_limited = False
        self.stopped_reason = "hang_fuse"


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


@dataclass(frozen=True)
class _SearchClock:
    """Clip and monotonic start that budget each ``Solve()``."""

    base_clip: SolveClip
    started_at: float

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at


@dataclass(frozen=True)
class _BandOrigin:
    """Maximization hit that anchors the near-best objective band."""

    objective: int
    hit: tuple[dict[str, int], dict[str, int]]


def _enumerate_objective_band(
    problem: InferenceProblem,
    built: BuiltModel,
    progress: StructuralSearchProgress,
    clock: _SearchClock,
    origin: _BandOrigin,
    *,
    hit_cap: int,
    cancel_token: InferenceCancelToken | None,
) -> None:
    """Enumerate ``[Z*-T, Z*]`` once and keep the best ``hit_cap`` signatures.

    The caller has already maximized once and posted the band plus a no-good for
    that first assignment. Clearing the objective makes the follow-up a
    satisfiability enumeration of the remaining band. Stop, effort, and hits
    are recorded on ``progress``.
    """
    advance = clock.base_clip.next_solve(
        effort_spent=progress.effort_spent,
        elapsed_seconds=clock.elapsed_seconds(),
        solve_wall_seconds=progress.solve_wall_seconds,
    )
    if advance.clip is None or advance.hang_fuse:
        if advance.hang_fuse:
            progress.hang_fuse_hit = True
            return
        progress.structural_hits = [origin.hit]
        progress.stopped_reason = "time_budget"
        progress.time_limited = True
        progress.top_solution_bucket_counts = _ranking_bin_indicators_by_action_id(
            problem, origin.hit[0]
        )
        return

    built.model.clear_objective()
    collector = _ObjectiveBandCollector(
        problem,
        built.merged_combo_catalog,
        built.action_count_vars,
        built.combo_count_vars,
        built.objective_var,
        first_objective=origin.objective,
        first_hit=origin.hit,
        hit_cap=hit_cap,
        cancel_token=cancel_token,
    )
    solver = cp_model.CpSolver()
    advance.clip.apply_to_solver(solver)
    solver.parameters.num_workers = configured_sat_search_workers()
    solver.parameters.enumerate_all_solutions = True
    wall_before = time.monotonic()
    status = invoke_cp_sat_solve(solver, built.model, collector)
    wall_delta = time.monotonic() - wall_before
    progress.last_solver_status = status
    progress.effort_spent += _solver_effort(solver)
    progress.solve_wall_seconds += wall_delta
    hits = [(actions, combos) for _objective, actions, combos in collector.best]
    progress.structural_hits = hits
    progress.top_solution_bucket_counts = (
        _ranking_bin_indicators_by_action_id(problem, hits[0][0]) if hits else {}
    )

    if collector.cancelled or (cancel_token is not None and cancel_token.is_cancelled()):
        progress.stopped_reason = "cancelled"
        progress.time_limited = False
        return

    decision = clock.base_clip.after_solve(
        solver_status=status,
        effort_spent=progress.effort_spent,
        solve_wall_seconds=progress.solve_wall_seconds,
        elapsed_seconds=clock.elapsed_seconds(),
        has_structural_hits=bool(hits),
    )
    if decision.hang_fuse:
        progress.hang_fuse_hit = True
        return
    # OPTIMAL/INFEASIBLE means the band was fully enumerated. A clip that also
    # happens to be numerically spent does not discard that completed set.
    if status not in (cp_model.OPTIMAL, cp_model.INFEASIBLE):
        progress.stopped_reason = "time_budget"
        progress.time_limited = True
        return
    progress.stopped_reason = (
        "max_solutions" if collector.found > hit_cap else "near_best_band_exhausted"
    )
    progress.time_limited = False


def _maximize_structural_hits(
    problem: InferenceProblem,
    built: BuiltModel,
    progress: StructuralSearchProgress,
    clock: _SearchClock,
    *,
    search_cap: int,
    cancel_token: InferenceCancelToken | None,
) -> int | None:
    """Maximize until ``search_cap`` hits. Returns the first objective, if any."""
    solver = cp_model.CpSolver()
    tier_max_objective: int | None = None
    max_objective: int | None = None
    near_best_band_applied = False
    near_best_threshold = problem.near_best_objective_threshold

    while len(progress.structural_hits) < search_cap:
        if cancel_token is not None and cancel_token.is_cancelled():
            progress.stopped_reason = "cancelled"
            break

        advance = clock.base_clip.next_solve(
            effort_spent=progress.effort_spent,
            elapsed_seconds=clock.elapsed_seconds(),
            solve_wall_seconds=progress.solve_wall_seconds,
        )
        if advance.clip is None:
            if advance.hang_fuse:
                progress.hang_fuse_hit = True
                progress.stopped_reason = "hang_fuse"
            else:
                progress.time_limited = True
                progress.stopped_reason = "time_budget"
            break
        advance.clip.apply_to_solver(solver)
        # Set only ``num_workers``. Setting both ``num_workers`` and the deprecated
        # ``num_search_workers`` to non-zero values makes OR-Tools return
        # MODEL_INVALID on this model (empty search; fleet warships stay "?").
        solver.parameters.num_workers = configured_sat_search_workers()
        callback = _StopSearchOnCancel(cancel_token) if cancel_token is not None else None
        wall_before = time.monotonic()
        progress.last_solver_status = invoke_cp_sat_solve(solver, built.model, callback)
        wall_delta = time.monotonic() - wall_before
        # Each Solve() reports only its own deterministic time.
        try:
            solve_effort = max(0.0, float(solver.deterministic_time))
        except RuntimeError:
            solve_effort = 0.0
        progress.effort_spent += solve_effort
        progress.solve_wall_seconds += wall_delta

        if cancel_token is not None and cancel_token.is_cancelled():
            progress.stopped_reason = "cancelled"
            break
        decision = clock.base_clip.after_solve(
            solver_status=progress.last_solver_status,
            effort_spent=progress.effort_spent,
            solve_wall_seconds=progress.solve_wall_seconds,
            elapsed_seconds=clock.elapsed_seconds(),
            has_structural_hits=bool(progress.structural_hits),
        )
        if decision.hang_fuse:
            progress.hang_fuse_hit = True
            progress.time_limited = False
            progress.stopped_reason = "hang_fuse"
            break
        if decision.time_limited:
            progress.time_limited = True
            progress.stopped_reason = "time_budget"

        if progress.last_solver_status not in _SUCCESS_STATUSES:
            if progress.time_limited:
                progress.stopped_reason = "time_budget"
            elif near_best_band_applied and progress.structural_hits:
                progress.stopped_reason = "near_best_band_exhausted"
            else:
                progress.stopped_reason = "infeasible"
            break

        action_counts = _read_action_counts(problem, built.action_count_vars, solver)
        combo_counts = _read_combo_counts(
            built.merged_combo_catalog, built.combo_count_vars, solver
        )
        progress.structural_hits.append((action_counts, combo_counts))
        progress.top_solution_bucket_counts = _ranking_bin_indicators_by_action_id(
            problem, action_counts
        )

        found_objective = int(solver.ObjectiveValue())
        if tier_max_objective is None:
            tier_max_objective = found_objective
            max_objective = found_objective
            built.model.add(built.objective_var >= tier_max_objective - near_best_threshold)
            near_best_band_applied = True
        else:
            max_objective = found_objective

        if near_best_band_applied and max_objective is not None:
            # Sliding ceiling: next maximize walks next-best inside [Z*-T, max].
            built.model.add(built.objective_var <= max_objective)

        add_no_good_cut(
            built.model,
            built.action_count_vars,
            built.combo_count_vars,
            action_counts,
            combo_counts,
            len(progress.structural_hits),
        )

        if len(progress.structural_hits) >= search_cap:
            progress.stopped_reason = "max_solutions"
            break

    return tier_max_objective


def collect_near_best_structural_hits(
    problem: InferenceProblem,
    *,
    built: BuiltModel,
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
            built.model,
            problem=problem,
            merged_combo_catalog=built.merged_combo_catalog,
            action_count_vars=built.action_count_vars,
            combo_count_vars=built.combo_count_vars,
            seed_solutions=seed_no_good_solutions,
        )
    else:
        seed_no_goods_applied, seed_no_goods_skipped = 0, 0

    progress = StructuralSearchProgress()
    clock = _SearchClock(
        base_clip=effective_solve_clip(
            solve_clip=problem.solve_clip,
            time_limit_seconds=problem.time_limit_seconds,
        ),
        started_at=time.monotonic(),
    )
    # Seed passes ask for one hit. A completed free search enumerates the band
    # after that first maximization instead of restarting once per hit.
    enumerate_band = (
        structural_hit_limit is None and not successive_search and problem.max_solutions > 1
    )
    if structural_hit_limit is None:
        search_cap = 1 if enumerate_band else problem.max_solutions
    else:
        search_cap = min(problem.max_solutions, structural_hit_limit)
    hit_cap = problem.max_solutions if enumerate_band else search_cap

    tier_max_objective = _maximize_structural_hits(
        problem,
        built,
        progress,
        clock,
        search_cap=search_cap,
        cancel_token=cancel_token,
    )
    if (
        enumerate_band
        and progress.structural_hits
        and tier_max_objective is not None
        and not progress.hang_fuse_hit
        and progress.stopped_reason != "cancelled"
        and not progress.time_limited
    ):
        _enumerate_objective_band(
            problem,
            built,
            progress,
            clock,
            _BandOrigin(objective=tier_max_objective, hit=progress.structural_hits[0]),
            hit_cap=hit_cap,
            cancel_token=cancel_token,
        )
    # Fuse fails closed: earlier hits in this search must not be admitted.
    progress.apply_hang_fuse_fail_closed()

    return NearBestStructuralSearchOutcome(
        structural_hits=progress.structural_hits,
        last_solver_status=progress.last_solver_status,
        stopped_reason=progress.stopped_reason,
        time_limited=progress.time_limited,
        hang_fuse_hit=progress.hang_fuse_hit,
        deterministic_time=progress.effort_spent,
        solve_wall_seconds=progress.solve_wall_seconds,
        tier_max_objective=tier_max_objective,
        near_best_threshold=problem.near_best_objective_threshold,
        seed_no_goods_applied=seed_no_goods_applied,
        seed_no_goods_skipped=seed_no_goods_skipped,
        top_solution_bucket_counts=progress.top_solution_bucket_counts,
    )
