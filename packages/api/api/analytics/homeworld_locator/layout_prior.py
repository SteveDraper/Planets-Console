"""Homeworld layout prior selection facade (#36 / #270).

Eligibility, sector build, cost ownership, and annotate stay here (or in sibling
shared modules). Discrete search is delegated to a replaceable ``LayoutPriorSolver``.
"""

from __future__ import annotations

import hashlib
import math
import struct
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from api.analytics.homeworld_locator.geometry import resolve_map_center
from api.analytics.homeworld_locator.layout_distributions_asset import (
    LayoutDistributionsAsset,
    load_default_layout_distributions_asset,
)
from api.analytics.homeworld_locator.layout_prior_anneal import AnnealingLayoutPriorSolver
from api.analytics.homeworld_locator.layout_prior_cost import (
    evaluate_layout_prior_selection,
    mid_stand_in_positions,
)
from api.analytics.homeworld_locator.layout_prior_enumerate import (
    MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR,
)
from api.analytics.homeworld_locator.layout_prior_problem import (
    LayoutPriorProblem,
    SectorLayoutState,
    build_layout_prior_problem,
    build_sector_layout_states,
)
from api.analytics.homeworld_locator.layout_prior_refine import refine_stand_in_positions
from api.analytics.homeworld_locator.layout_prior_report import (
    LayoutPriorTimingMs,
    build_projected_selection_report,
)
from api.analytics.homeworld_locator.layout_prior_run_history import record_layout_prior_report
from api.analytics.homeworld_locator.layout_prior_solver import (
    LAYOUT_PRIOR_SOLVER_ANNEAL,
    LAYOUT_PRIOR_SOLVER_ENUMERATE,
    LayoutPriorSolution,
    LayoutPriorSolver,
    LayoutPriorSolveResult,
    layout_prior_solver_from_config,
    layout_prior_solver_from_name,
    layout_prior_stop_gate_from_config,
)
from api.analytics.homeworld_locator.layout_prior_stop_gate import (
    DeadlineStopGate,
    MaxStepsStopGate,
    NeverStopGate,
    StopGate,
)
from api.analytics.homeworld_locator.models import OriginDistanceObservation
from api.analytics.homeworld_locator.sector_overlays import (
    homeworld_layout_asset_category,
    homeworld_sector_emission_eligible,
    resolve_viewpoint_pin_planet,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord, HomeworldCandidateView
from api.analytics.turn_roster import players_by_id
from api.concepts.visibility_coverage import planet_scan_origins, visibility_owner_ids
from api.config import get_config
from api.models.game import TurnInfo

__all__ = [
    "LAYOUT_PRIOR_SOLVER_ANNEAL",
    "LAYOUT_PRIOR_SOLVER_ENUMERATE",
    "MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR",
    "LayoutPriorProblem",
    "LayoutPriorSolution",
    "LayoutPriorSolver",
    "ProjectedLayoutSelection",
    "SectorLayoutState",
    "apply_layout_prior_most_probable",
    "build_sector_layout_states",
    "fresh_layout_prior_stop_gate",
    "layout_prior_continuity_rng_seed_turns",
    "layout_prior_evidence_fingerprint",
    "layout_prior_input_fingerprint",
    "layout_prior_solver_from_config",
    "layout_prior_solver_from_name",
    "layout_prior_stop_gate_from_config",
    "score_projected_layout_selection",
    "select_best_layout_prior_solve_result",
    "try_layout_prior_problem",
    "try_project_previous_layout_selection",
]


def layout_prior_input_fingerprint(
    candidates: Sequence[HomeworldCandidateRecord],
) -> tuple[tuple[int, str, int | None], ...]:
    """Stable fingerprint of the post-promote/cull candidate set that feeds selection.

    Soft-evidence λ and observation identity are sibling reuse keys
    (``layout_prior_evidence_lambda`` / ``evidenceLambda``,
    ``layout_prior_evidence_fingerprint`` / ``evidenceFingerprint``), not part of
    this candidate tuple -- all must match for layout-prior selection reuse.
    """
    return tuple(
        sorted((row.planet_id, row.confidence_tier, row.perspective) for row in candidates)
    )


def layout_prior_evidence_fingerprint(
    observations: Sequence[OriginDistanceObservation],
) -> str:
    """Constant-size SHA-256 hex digest of soft OD observation identity.

    Hash effective observations (after through-turn freeze filtering). Order is
    canonicalized so callers need not pre-sort. Empty input yields the empty
    digest (stable miss / no-evidence key).
    """
    hasher = hashlib.sha256()
    for observation in sorted(
        observations,
        key=lambda row: (row.turn, row.x, row.y, row.matched_planet_ids),
    ):
        hasher.update(struct.pack(">iii", observation.turn, observation.x, observation.y))
        hasher.update(struct.pack(">I", len(observation.matched_planet_ids)))
        for planet_id in observation.matched_planet_ids:
            hasher.update(struct.pack(">i", planet_id))
    return hasher.hexdigest()


def try_layout_prior_problem(
    candidates: Sequence[HomeworldCandidateRecord],
    *,
    turn: TurnInfo,
    view: HomeworldCandidateView,
    player_count: int | None = None,
    layout_asset: LayoutDistributionsAsset | None = None,
    map_center: tuple[float, float] | None = None,
    origin_distance_observations: Sequence[OriginDistanceObservation] | None = None,
    origin_distance_evidence_lambda: float | None = None,
) -> LayoutPriorProblem | None:
    """Build a solver problem from turn + view, or ``None`` when the emission gate fails.

    Gate failures include missing pin, ineligible map geometry, or no layout
    distribution category. Callers that annotate (facade) clear
    ``is_most_probable`` on ``None``; callers that probe may raise.
    Soft evidence observations default from ``view.origin_distance_observations``
    (populated from the shell evidence aggregate at materialize); λ defaults from
    config when omitted (absolute-turn update weight ``w(t)=λ^t``).
    """
    resolved_count = player_count if player_count is not None else len(players_by_id(turn))
    pin = resolve_viewpoint_pin_planet(view, turn.planets)
    if pin is None or not homeworld_sector_emission_eligible(
        turn, pin=pin, player_count=resolved_count
    ):
        return None

    category = homeworld_layout_asset_category(turn, player_count=resolved_count)
    if category is None:
        return None

    asset = layout_asset if layout_asset is not None else load_default_layout_distributions_asset()
    distributions = asset.for_category(category)
    center = map_center if map_center is not None else resolve_map_center(turn.planets)
    r_inner, r_outer = asset.center_distance_band(category)
    center_x, center_y = center
    pin_angle = math.atan2(pin.y - center_y, pin.x - center_x)
    half = math.pi / resolved_count
    width = (2.0 * math.pi) / resolved_count

    planets_by_id = {planet.id: planet for planet in turn.planets}
    owner_ids = visibility_owner_ids(turn.player.id, turn.relations)
    scan_origins = planet_scan_origins(
        turn.planets,
        turn.ships,
        turn.hulls,
        owner_ids,
        planet_scan_range=float(turn.settings.planetscanrange),
    )
    observations = (
        tuple(view.origin_distance_observations)
        if origin_distance_observations is None
        else tuple(origin_distance_observations)
    )
    evidence_lambda = (
        get_config().homeworld_locator.origin_distance_evidence_lambda
        if origin_distance_evidence_lambda is None
        else origin_distance_evidence_lambda
    )
    return build_layout_prior_problem(
        candidates=candidates,
        planets_by_id=planets_by_id,
        pin=pin,
        pin_angle=pin_angle,
        player_count=resolved_count,
        center=center,
        r_inner=r_inner,
        r_outer=r_outer,
        half=half,
        width=width,
        scan_origins=scan_origins,
        nebulas=turn.nebulas,
        distributions=distributions,
        seed_game_id=int(turn.game.id),
        seed_turn=int(turn.settings.turn),
        seed_perspective=int(turn.player.id),
        seed_input_fingerprint=layout_prior_input_fingerprint(candidates),
        layout_category=category,
        origin_distance_observations=observations,
        origin_distance_evidence_lambda=evidence_lambda,
    )


def apply_layout_prior_most_probable(
    candidates: Sequence[HomeworldCandidateRecord],
    *,
    turn: TurnInfo,
    view: HomeworldCandidateView,
    player_count: int | None = None,
    layout_asset: LayoutDistributionsAsset | None = None,
    map_center: tuple[float, float] | None = None,
    solver: LayoutPriorSolver | None = None,
    stop_gate: StopGate | None = None,
    origin_distance_observations: Sequence[OriginDistanceObservation] | None = None,
    origin_distance_evidence_lambda: float | None = None,
    previous_most_probable_planet_ids: Sequence[int] | None = None,
) -> tuple[HomeworldCandidateRecord, ...]:
    """Annotate ``is_most_probable`` after evidence culls when the emission gate passes.

    Anneal runs two inline solves when ``seed_turn > 1``: previous-turn RNG seed
    and this-turn RNG seed, each with a fresh full-budget stop-gate. When the
    previous shell selection is still a complete admissible assignment under
    this turn's choice sectors, it is scored (cheap; no SA) and preferred when
    strictly better than both anneals. Enumerate stays a single solve.
    """
    problem = try_layout_prior_problem(
        candidates,
        turn=turn,
        view=view,
        player_count=player_count,
        layout_asset=layout_asset,
        map_center=map_center,
        origin_distance_observations=origin_distance_observations,
        origin_distance_evidence_lambda=origin_distance_evidence_lambda,
    )
    if problem is None:
        return tuple(
            replace(row, is_most_probable=False) if row.is_most_probable else row
            for row in candidates
        )

    resolved_solver = solver if solver is not None else layout_prior_solver_from_config()
    if stop_gate is not None:
        template_gate = stop_gate
    elif solver is not None:
        # Injected solvers (tests / fakes): enumerate/fakes may use never-stop.
        # Anneal must terminate -- use the configured wall-clock budget.
        template_gate = _default_stop_gate_for_injected_solver(resolved_solver)
    else:
        template_gate = layout_prior_stop_gate_from_config()

    result = _solve_layout_prior_for_annotation(
        resolved_solver,
        problem,
        template_gate=template_gate,
        previous_most_probable_planet_ids=previous_most_probable_planet_ids,
    )
    most_probable_ids = frozenset(result.solution.chosen_planet_ids_by_sector.values())
    return tuple(
        replace(row, is_most_probable=row.planet_id in most_probable_ids) for row in candidates
    )


def layout_prior_continuity_rng_seed_turns(shell_turn: int) -> tuple[int, ...]:
    """RNG seed turns for deliberate dual-seed anneal continuity.

    When ``shell_turn > 1``, return ``(shell_turn - 1, shell_turn)`` so the
    facade runs two full-budget inline solves -- not a single warm-started
    anneal. Roles:

    - Previous-turn seed: maintains SA dynamics where local evidence is
      unchanged (same RNG stream as last turn's this-seed solve).
    - This-turn seed: variation / exploration under a fresh stream.

    Projection of the previous selection is a separate continuity mechanism
    (see ``_solve_layout_prior_for_annotation``).
    """
    if shell_turn <= 1:
        return (shell_turn,)
    return (shell_turn - 1, shell_turn)


def try_project_previous_layout_selection(
    problem: LayoutPriorProblem,
    previous_most_probable_planet_ids: Sequence[int],
) -> dict[int, int] | None:
    """Map a prior selection onto this problem's choice sectors, or ``None``.

    Continuity projection (deliberate, not a warm-start substitute for dual SA):
    when the previous set remains a complete admissible assignment, score it on
    current criteria for stability against SA noise.

    Admissible when every previous planet is still a legal choice in exactly one
    current choice sector, every choice sector gets exactly one such planet, and
    there are no leftover previous planets.
    """
    if not previous_most_probable_planet_ids:
        return None
    previous = set(previous_most_probable_planet_ids)
    chosen: dict[int, int] = {}
    for state in problem.sector_states:
        if state.kind != "choice":
            continue
        hits = [planet_id for planet_id in state.choice_planet_ids if planet_id in previous]
        if len(hits) != 1:
            return None
        chosen[state.sector_index] = hits[0]
    if set(chosen.values()) != previous:
        return None
    return chosen


@dataclass(frozen=True)
class ProjectedLayoutSelection:
    """A scored continuity projection plus the wall time scoring it cost."""

    solution: LayoutPriorSolution
    timing: LayoutPriorTimingMs


def score_projected_layout_selection(
    problem: LayoutPriorProblem,
    chosen_by_sector: Mapping[int, int],
) -> ProjectedLayoutSelection | None:
    """Score an admissible prior assignment (refine path; no SA).

    Used so a still-legal previous selection can beat both continuity anneals
    when it scores better -- stability against SA noise, not a search shortcut.
    Timing covers the stand-in refine and final evaluation this path actually
    runs, so a projection win reports its own cost rather than zeros.
    """
    total_t0 = time.perf_counter()
    stand_in_sectors = [state for state in problem.sector_states if state.kind == "stand_in"]
    mid_stand_ins = mid_stand_in_positions(stand_in_sectors)
    refine_t0 = time.perf_counter()
    refined = refine_stand_in_positions(
        problem,
        chosen_by_sector,
        initial_stand_in_positions=mid_stand_ins,
    )
    refine_ms = (time.perf_counter() - refine_t0) * 1000.0
    stand_ins = refined or mid_stand_ins
    scored = evaluate_layout_prior_selection(
        problem, chosen_by_sector, stand_in_positions=stand_ins
    )
    if scored is None:
        return None
    cost, tie_key = scored
    return ProjectedLayoutSelection(
        solution=LayoutPriorSolution(
            chosen_planet_ids_by_sector=dict(chosen_by_sector),
            stand_in_positions_by_sector=stand_ins,
            cost=cost,
            tie_key=tie_key,
        ),
        timing=LayoutPriorTimingMs(
            greedy_ms=0.0,
            sa_ms=0.0,
            refine_ms=refine_ms,
            total_ms=(time.perf_counter() - total_t0) * 1000.0,
        ),
    )


def select_best_layout_prior_solve_result(
    results: Sequence[LayoutPriorSolveResult],
) -> LayoutPriorSolveResult:
    """Pick the lowest-cost solve; ties use the existing lexicographic tie-key."""
    if not results:
        raise ValueError("select_best_layout_prior_solve_result requires at least one result")
    best = results[0]
    for candidate in results[1:]:
        if _layout_prior_solution_is_better(candidate.solution, best.solution):
            best = candidate
    return best


def _solve_layout_prior_for_annotation(
    solver: LayoutPriorSolver,
    problem: LayoutPriorProblem,
    *,
    template_gate: StopGate,
    previous_most_probable_planet_ids: Sequence[int] | None = None,
) -> LayoutPriorSolveResult:
    """Anneal continuity facade: dual-seed SA, then optional prior projection.

    Deliberate three-part design (do not collapse to a single warm-started anneal):

    1. This-turn RNG seed -- variation / exploration.
    2. Previous-turn RNG seed -- maintains SA dynamics where local evidence is
       unchanged (replay of last turn's this-seed stream).
    3. Score admissible previous selection (projection, no SA) -- stability
       against SA noise; prefer when better than both anneals by cost/tie-key.
    """
    if not isinstance(solver, AnnealingLayoutPriorSolver):
        result = solver.solve(problem, stop_gate=fresh_layout_prior_stop_gate(template_gate))
        record_layout_prior_report(result.report)
        return result

    results: list[LayoutPriorSolveResult] = []
    for rng_turn in layout_prior_continuity_rng_seed_turns(problem.seed_turn):
        seeded = replace(problem, rng_seed_turn=rng_turn)
        result = solver.solve(seeded, stop_gate=fresh_layout_prior_stop_gate(template_gate))
        results.append(result)
    best = select_best_layout_prior_solve_result(results)

    projected_chosen = try_project_previous_layout_selection(
        problem,
        () if previous_most_probable_planet_ids is None else previous_most_probable_planet_ids,
    )
    winner = best
    if projected_chosen is not None:
        projected = score_projected_layout_selection(problem, projected_chosen)
        if projected is not None and _layout_prior_solution_is_better(
            projected.solution, best.solution
        ):
            winner = LayoutPriorSolveResult(
                solution=projected.solution,
                report=build_projected_selection_report(
                    cost=projected.solution.cost,
                    tie_key=projected.solution.tie_key,
                    timing=projected.timing,
                    reference_report=best.report,
                ),
            )
    # One diagnostics entry per continuity round (winning anneal or projection).
    record_layout_prior_report(winner.report)
    return winner


def _layout_prior_solution_is_better(
    candidate: LayoutPriorSolution,
    incumbent: LayoutPriorSolution,
) -> bool:
    if candidate.cost < incumbent.cost - 1e-12:
        return True
    if abs(candidate.cost - incumbent.cost) <= 1e-12 and candidate.tie_key < incumbent.tie_key:
        return True
    return False


def fresh_layout_prior_stop_gate(template: StopGate) -> StopGate:
    """Unused stop-gate with the same budget/kind as ``template``.

    Dual-seed anneal must not share a mutable gate instance across solves.
    Unknown gate types raise rather than returning ``template``.
    """
    if isinstance(template, DeadlineStopGate):
        return DeadlineStopGate(template.budget_ms)
    if isinstance(template, MaxStepsStopGate):
        return MaxStepsStopGate(template.max_steps)
    if isinstance(template, NeverStopGate):
        return NeverStopGate()
    raise ValueError(
        "fresh_layout_prior_stop_gate cannot clone "
        f"{type(template).__name__}; use DeadlineStopGate, MaxStepsStopGate, "
        "or NeverStopGate"
    )


def _default_stop_gate_for_injected_solver(solver: LayoutPriorSolver) -> StopGate:
    """Safe default gate when a caller injects a solver without ``stop_gate``.

    ``NeverStopGate`` is correct for the exhaustive enumerator (and most fakes).
    Anneal would hang forever on that gate, so use the configured deadline budget.
    """
    if isinstance(solver, AnnealingLayoutPriorSolver):
        return DeadlineStopGate(get_config().homeworld_locator.layout_prior_budget_ms)
    return NeverStopGate()
