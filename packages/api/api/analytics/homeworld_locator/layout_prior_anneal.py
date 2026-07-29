"""Greedy-init + seeded size-aware simulated annealing layout-prior solver (#270)."""

from __future__ import annotations

import hashlib
import math
import random
import struct
import time
from collections.abc import Mapping, Sequence

from api.analytics.homeworld_locator.constants import LAYOUT_PRIOR_ALGORITHM_VERSION
from api.analytics.homeworld_locator.layout_prior_cost import (
    evaluate_layout_prior_selection,
    fixed_and_slot_anchored,
    mid_stand_in_positions,
)
from api.analytics.homeworld_locator.layout_prior_problem import (
    LayoutPriorProblem,
    SectorLayoutState,
)
from api.analytics.homeworld_locator.layout_prior_refine import refine_stand_in_positions
from api.analytics.homeworld_locator.layout_prior_report import (
    LayoutPriorSearchStats,
    LayoutPriorStopReason,
    LayoutPriorTimingMs,
    build_run_report,
    downsample_incumbent_series,
    problem_size_hints,
)
from api.analytics.homeworld_locator.layout_prior_solver import (
    LAYOUT_PRIOR_SOLVER_ANNEAL,
    LayoutPriorSolution,
    LayoutPriorSolveResult,
)
from api.analytics.homeworld_locator.layout_prior_stop_gate import (
    DeadlineStopGate,
    MaxStepsStopGate,
    StopGate,
    stop_gate_budget_progress,
    stop_gate_info,
)
from api.analytics.homeworld_locator.sector_overlays import sector_band_geometric_center
from api.concepts.stellar_cartography.nebula_visibility import distance_ly

# Proposal bias: weight ~ 1 / (eps + distance_to_mid)^power
_PROPOSAL_DISTANCE_EPS = 1.0
_PROPOSAL_DISTANCE_POWER = 1.5
# Final / initial temperature ratio for budget-progress geometric schedule.
_TEMPERATURE_FINAL_RATIO = 1.0e-3


class AnnealingLayoutPriorSolver:
    """Greedy frontier init, then seeded SA, then sample-grid stand-in refine.

    During SA, stand-ins stay at fixed mid placeholders. Refine runs after the
    stop-gate ends and is not polled by the gate.
    """

    def solve(
        self,
        problem: LayoutPriorProblem,
        *,
        stop_gate: StopGate,
    ) -> LayoutPriorSolveResult:
        total_t0 = time.perf_counter()
        sector_states = problem.sector_states
        choice_sectors = [state for state in sector_states if state.kind == "choice"]
        stand_in_sectors = [state for state in sector_states if state.kind == "stand_in"]
        mid_stand_ins = mid_stand_in_positions(stand_in_sectors)
        size = problem_size_hints(
            choice_sector_count=len(choice_sectors),
            total_possibles=sum(len(state.choice_planet_ids) for state in choice_sectors),
            stand_in_sector_count=len(stand_in_sectors),
            planet_count=len(problem.planets_by_id),
            category=problem.layout_category,
        )
        gate_info = stop_gate_info(stop_gate)

        if not choice_sectors:
            refine_t0 = time.perf_counter()
            refined = refine_stand_in_positions(
                problem,
                {},
                initial_stand_in_positions=mid_stand_ins,
            )
            refine_ms = (time.perf_counter() - refine_t0) * 1000.0
            scored = evaluate_layout_prior_selection(
                problem, {}, stand_in_positions=refined or mid_stand_ins
            )
            cost = 0.0 if scored is None else scored[0]
            tie_key = () if scored is None else scored[1]
            solution = LayoutPriorSolution(
                chosen_planet_ids_by_sector={},
                stand_in_positions_by_sector=refined or mid_stand_ins,
                cost=cost,
                tie_key=tie_key,
            )
            total_ms = (time.perf_counter() - total_t0) * 1000.0
            report = build_run_report(
                game_id=problem.seed_game_id,
                turn=problem.seed_turn,
                perspective=problem.seed_perspective,
                solver=LAYOUT_PRIOR_SOLVER_ANNEAL,
                stop_gate=gate_info,
                stop_reason="no_choices",
                timing=LayoutPriorTimingMs(
                    greedy_ms=0.0, sa_ms=0.0, refine_ms=refine_ms, total_ms=total_ms
                ),
                search=LayoutPriorSearchStats(
                    sa_steps_attempted=0,
                    sa_steps_accepted=0,
                    greedy_cost=cost,
                    pre_refine_cost=cost,
                    final_cost=cost,
                    tie_key=tie_key,
                ),
                problem_size=size,
                incumbent_cost_series=(),
            )
            return LayoutPriorSolveResult(solution=solution, report=report)

        greedy_t0 = time.perf_counter()
        chosen = greedy_frontier_init(problem, choice_sectors, mid_stand_ins)
        greedy_ms = (time.perf_counter() - greedy_t0) * 1000.0
        scored = evaluate_layout_prior_selection(problem, chosen, stand_in_positions=mid_stand_ins)
        if scored is None:
            total_ms = (time.perf_counter() - total_t0) * 1000.0
            solution = LayoutPriorSolution(
                chosen_planet_ids_by_sector={},
                stand_in_positions_by_sector=mid_stand_ins,
                cost=0.0,
                tie_key=(),
            )
            report = build_run_report(
                game_id=problem.seed_game_id,
                turn=problem.seed_turn,
                perspective=problem.seed_perspective,
                solver=LAYOUT_PRIOR_SOLVER_ANNEAL,
                stop_gate=gate_info,
                stop_reason="no_choices",
                timing=LayoutPriorTimingMs(
                    greedy_ms=greedy_ms, sa_ms=0.0, refine_ms=0.0, total_ms=total_ms
                ),
                search=LayoutPriorSearchStats(
                    sa_steps_attempted=0,
                    sa_steps_accepted=0,
                    greedy_cost=0.0,
                    pre_refine_cost=0.0,
                    final_cost=0.0,
                    tie_key=(),
                ),
                problem_size=size,
                incumbent_cost_series=(),
            )
            return LayoutPriorSolveResult(solution=solution, report=report)

        best_cost, best_tie = scored
        best_chosen = dict(chosen)
        current_cost = best_cost
        current_chosen = dict(chosen)
        greedy_cost = best_cost
        incumbent_samples: list[tuple[int, float]] = [(0, best_cost)]

        rng = random.Random(layout_prior_rng_seed(problem))
        t0 = initial_temperature(problem, choice_sectors)
        sector_mids = {
            state.sector_index: sector_band_geometric_center(
                center=problem.center,
                angle_start=state.angle_start,
                angle_end=state.angle_end,
                r_inner=problem.r_inner,
                r_outer=problem.r_outer,
            )
            for state in choice_sectors
        }

        sa_t0 = time.perf_counter()
        sa_steps_attempted = 0
        sa_steps_accepted = 0
        neighborhood_exhausted = False
        while not stop_gate.should_stop():
            temperature = temperature_at_progress(t0, stop_gate_budget_progress(stop_gate))
            proposal = propose_neighbor(
                current_chosen,
                choice_sectors,
                problem,
                sector_mids,
                rng,
            )
            if proposal is None:
                # No movable multi-planet choice sectors: discrete neighborhood is empty.
                neighborhood_exhausted = True
                break
            sa_steps_attempted += 1
            proposed_chosen, _sector_index, _planet_id = proposal
            proposed_scored = evaluate_layout_prior_selection(
                problem, proposed_chosen, stand_in_positions=mid_stand_ins
            )
            if proposed_scored is None:
                continue
            proposed_cost, proposed_tie = proposed_scored
            delta = proposed_cost - current_cost
            accept = delta <= 0.0 or (
                temperature > 1e-15 and rng.random() < math.exp(-delta / temperature)
            )
            if accept:
                sa_steps_accepted += 1
                current_chosen = proposed_chosen
                current_cost = proposed_cost
                if proposed_cost < best_cost - 1e-12 or (
                    abs(proposed_cost - best_cost) <= 1e-12 and proposed_tie < best_tie
                ):
                    best_cost = proposed_cost
                    best_tie = proposed_tie
                    best_chosen = dict(proposed_chosen)
                    incumbent_samples.append((sa_steps_attempted, best_cost))
        sa_ms = (time.perf_counter() - sa_t0) * 1000.0
        pre_refine_cost = best_cost
        stop_reason = _anneal_stop_reason(stop_gate, neighborhood_exhausted=neighborhood_exhausted)

        refine_t0 = time.perf_counter()
        refined = refine_stand_in_positions(
            problem,
            best_chosen,
            initial_stand_in_positions=mid_stand_ins,
        )
        refine_ms = (time.perf_counter() - refine_t0) * 1000.0
        final_scored = evaluate_layout_prior_selection(
            problem, best_chosen, stand_in_positions=refined or mid_stand_ins
        )
        final_cost = best_cost if final_scored is None else final_scored[0]
        final_tie = best_tie if final_scored is None else final_scored[1]
        solution = LayoutPriorSolution(
            chosen_planet_ids_by_sector=best_chosen,
            stand_in_positions_by_sector=refined or mid_stand_ins,
            cost=final_cost,
            tie_key=final_tie,
        )
        total_ms = (time.perf_counter() - total_t0) * 1000.0
        report = build_run_report(
            game_id=problem.seed_game_id,
            turn=problem.seed_turn,
            perspective=problem.seed_perspective,
            solver=LAYOUT_PRIOR_SOLVER_ANNEAL,
            stop_gate=gate_info,
            stop_reason=stop_reason,
            timing=LayoutPriorTimingMs(
                greedy_ms=greedy_ms, sa_ms=sa_ms, refine_ms=refine_ms, total_ms=total_ms
            ),
            search=LayoutPriorSearchStats(
                sa_steps_attempted=sa_steps_attempted,
                sa_steps_accepted=sa_steps_accepted,
                greedy_cost=greedy_cost,
                pre_refine_cost=pre_refine_cost,
                final_cost=final_cost,
                tie_key=final_tie,
                last_incumbent_improvement_step=incumbent_samples[-1][0],
            ),
            problem_size=size,
            incumbent_cost_series=downsample_incumbent_series(incumbent_samples),
        )
        return LayoutPriorSolveResult(solution=solution, report=report)


def _anneal_stop_reason(
    stop_gate: StopGate,
    *,
    neighborhood_exhausted: bool,
) -> LayoutPriorStopReason:
    if neighborhood_exhausted:
        return "exhausted"
    if isinstance(stop_gate, DeadlineStopGate) and stop_gate.has_fired():
        return "deadline"
    if isinstance(stop_gate, MaxStepsStopGate) and stop_gate.has_fired():
        return "max_steps"
    return "exhausted"


def layout_prior_rng_seed(problem: LayoutPriorProblem) -> int:
    """Deterministic 64-bit seed from scope + fingerprint + algorithm version."""
    hasher = hashlib.sha256()
    hasher.update(struct.pack(">q", int(problem.seed_game_id)))
    hasher.update(struct.pack(">q", int(problem.seed_turn)))
    hasher.update(struct.pack(">q", int(problem.seed_perspective)))
    hasher.update(struct.pack(">q", int(LAYOUT_PRIOR_ALGORITHM_VERSION)))
    for planet_id, tier, perspective in problem.seed_input_fingerprint:
        hasher.update(struct.pack(">q", int(planet_id)))
        hasher.update(tier.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(struct.pack(">q", -1 if perspective is None else int(perspective)))
    return int.from_bytes(hasher.digest()[:8], "big")


def initial_temperature(
    problem: LayoutPriorProblem,
    choice_sectors: Sequence[SectorLayoutState],
) -> float:
    """Size-aware starting temperature (in-code coefficients, not YAML)."""
    n_choice = max(1, len(choice_sectors))
    n_possibles = max(1, sum(len(state.choice_planet_ids) for state in choice_sectors))
    n_planets = max(1, len(problem.planets_by_id))
    # Scale with log of search breadth so larger rings explore longer.
    return 8.0 + 4.0 * math.log1p(n_possibles) + 0.5 * math.log1p(n_choice * n_planets)


def temperature_at_progress(t0: float, progress: float) -> float:
    """Budget-progress geometric cool: ``T = T0 * (T_final/T0)^progress``.

    Progress is the fraction of wall-clock or step budget consumed (0..1).
    ``T_final = T0 * _TEMPERATURE_FINAL_RATIO`` so uphill moves stay viable
    through most of the budget instead of collapsing after a few thousand
    per-step multiplies.
    """
    clamped = min(1.0, max(0.0, progress))
    if t0 <= 0.0:
        return 0.0
    return t0 * (_TEMPERATURE_FINAL_RATIO**clamped)


def greedy_frontier_init(
    problem: LayoutPriorProblem,
    choice_sectors: Sequence[SectorLayoutState],
    mid_stand_ins: Mapping[int, tuple[float, float]],
) -> dict[int, int]:
    """Grow from pinned/fixed sectors: fewest-possibles frontier, min-cost planet."""
    player_count = len(problem.sector_states)
    fixed_by_sector, _slot_anchored = fixed_and_slot_anchored(problem.sector_states)
    assigned: set[int] = set(fixed_by_sector)
    chosen: dict[int, int] = {}
    choice_by_index = {state.sector_index: state for state in choice_sectors}
    remaining = set(choice_by_index)

    while remaining:
        frontier = _frontier_choice_sectors(assigned, remaining, player_count)
        if not frontier:
            # No pins yet, or disconnected choice set: lowest remaining index.
            frontier = {min(remaining)}

        def sector_key(sector_index: int) -> tuple[int, int]:
            state = choice_by_index[sector_index]
            return (len(state.choice_planet_ids), sector_index)

        sector_index = min(frontier, key=sector_key)
        state = choice_by_index[sector_index]
        best_planet: int | None = None
        best_cost = float("inf")
        for planet_id in state.choice_planet_ids:
            trial = dict(chosen)
            trial[sector_index] = planet_id
            cost = _partial_ring_cost(
                problem,
                trial,
                mid_stand_ins=mid_stand_ins,
            )
            if cost < best_cost - 1e-12 or (
                abs(cost - best_cost) <= 1e-12 and (best_planet is None or planet_id < best_planet)
            ):
                best_cost = cost
                best_planet = planet_id
        if best_planet is None:
            # No scorable planet; fall back to lowest id.
            best_planet = min(state.choice_planet_ids)
        chosen[sector_index] = best_planet
        assigned.add(sector_index)
        remaining.discard(sector_index)

    return chosen


def propose_neighbor(
    current: Mapping[int, int],
    choice_sectors: Sequence[SectorLayoutState],
    problem: LayoutPriorProblem,
    sector_mids: Mapping[int, tuple[float, float]],
    rng: random.Random,
) -> tuple[dict[int, int], int, int] | None:
    """Propose replacing one choice-sector planet, biased toward nearer mid."""
    movable = [state for state in choice_sectors if len(state.choice_planet_ids) > 1]
    if not movable:
        return None
    state = movable[rng.randrange(len(movable))]
    current_planet = current[state.sector_index]
    alternatives = [pid for pid in state.choice_planet_ids if pid != current_planet]
    if not alternatives:
        return None
    mid = sector_mids[state.sector_index]
    weights = [_proposal_weight(pid, problem, mid) for pid in alternatives]
    planet_id = _weighted_choice(rng, alternatives, weights)
    proposed = dict(current)
    proposed[state.sector_index] = planet_id
    return proposed, state.sector_index, planet_id


def _proposal_weight(
    planet_id: int,
    problem: LayoutPriorProblem,
    sector_mid: tuple[float, float],
) -> float:
    planet = problem.planets_by_id.get(planet_id)
    if planet is None:
        return 1e-9
    dist = distance_ly(planet.x, planet.y, sector_mid[0], sector_mid[1])
    return 1.0 / ((_PROPOSAL_DISTANCE_EPS + dist) ** _PROPOSAL_DISTANCE_POWER)


def _weighted_choice(
    rng: random.Random,
    items: Sequence[int],
    weights: Sequence[float],
) -> int:
    total = sum(weights)
    if total <= 0.0:
        return items[rng.randrange(len(items))]
    pick = rng.random() * total
    cumulative = 0.0
    for item, weight in zip(items, weights, strict=True):
        cumulative += weight
        if pick <= cumulative:
            return item
    return items[-1]


def _frontier_choice_sectors(
    assigned: set[int],
    remaining: set[int],
    player_count: int,
) -> set[int]:
    """Choice sectors adjacent on the circular ring to the assigned set."""
    frontier: set[int] = set()
    for index in assigned:
        left = (index - 1) % player_count
        right = (index + 1) % player_count
        if left in remaining:
            frontier.add(left)
        if right in remaining:
            frontier.add(right)
    return frontier


def _partial_ring_cost(
    problem: LayoutPriorProblem,
    chosen_by_sector: Mapping[int, int],
    *,
    mid_stand_ins: Mapping[int, tuple[float, float]],
) -> float:
    """Layout-prior cost over fixed + assigned choices + mid stand-ins only."""
    scored = evaluate_layout_prior_selection(
        problem,
        chosen_by_sector,
        stand_in_positions=mid_stand_ins,
    )
    return float("inf") if scored is None else scored[0]
