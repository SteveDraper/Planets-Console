"""Capped product layout-prior solver (#36 enumerator)."""

from __future__ import annotations

from itertools import product

from api.analytics.homeworld_locator.layout_prior_cost import (
    evaluate_layout_prior_selection,
    mid_stand_in_positions,
)
from api.analytics.homeworld_locator.layout_prior_problem import (
    LayoutPriorProblem,
    SectorLayoutState,
)
from api.analytics.homeworld_locator.layout_prior_solver import LayoutPriorSolution
from api.analytics.homeworld_locator.layout_prior_stop_gate import StopGate
from api.analytics.homeworld_locator.sector_overlays import sector_band_geometric_center
from api.concepts.stellar_cartography.nebula_visibility import distance_ly

# Bound joint enumeration: keep the nearest candidates to each sector mid.
MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR = 4


class EnumeratingLayoutPriorSolver:
    """Exhaustive product over ≤4 nearest-mid possibles per choice sector.

    Uses fixed mid stand-in placeholders from the problem. Ignores ``stop_gate``
    (enumeration is finite and already capped).
    """

    def solve(
        self,
        problem: LayoutPriorProblem,
        *,
        stop_gate: StopGate,
    ) -> LayoutPriorSolution:
        del stop_gate  # Enumerator does not poll; retained for protocol parity.
        sector_states = problem.sector_states
        choice_sectors = [state for state in sector_states if state.kind == "choice"]
        stand_in_sectors = [state for state in sector_states if state.kind == "stand_in"]
        stand_in_positions = mid_stand_in_positions(stand_in_sectors)
        if not choice_sectors:
            return LayoutPriorSolution(
                chosen_planet_ids_by_sector={},
                stand_in_positions_by_sector=stand_in_positions,
                cost=0.0,
                tie_key=(),
            )

        choice_options = [nearest_mid_choice_ids(sector, problem) for sector in choice_sectors]

        best_cost = float("inf")
        best_tie_key: tuple[tuple[int, int], ...] = ()
        best_choices: dict[int, int] = {}

        for combo in product(*choice_options):
            chosen_by_sector = {
                sector.sector_index: planet_id
                for sector, planet_id in zip(choice_sectors, combo, strict=True)
            }
            scored = evaluate_layout_prior_selection(
                problem,
                chosen_by_sector,
                stand_in_positions=stand_in_positions,
            )
            if scored is None:
                continue
            cost, tie_key = scored
            if cost < best_cost - 1e-12 or (
                abs(cost - best_cost) <= 1e-12 and tie_key < best_tie_key
            ):
                best_cost = cost
                best_tie_key = tie_key
                best_choices = chosen_by_sector

        return LayoutPriorSolution(
            chosen_planet_ids_by_sector=best_choices,
            stand_in_positions_by_sector=stand_in_positions,
            cost=best_cost if best_choices else 0.0,
            tie_key=best_tie_key,
        )


def nearest_mid_choice_ids(
    sector: SectorLayoutState,
    problem: LayoutPriorProblem,
) -> tuple[int, ...]:
    """Cap a choice sector to the ≤N nearest planets to the sector mid."""
    if len(sector.choice_planet_ids) <= MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR:
        return sector.choice_planet_ids

    sector_mid = sector_band_geometric_center(
        center=problem.center,
        angle_start=sector.angle_start,
        angle_end=sector.angle_end,
        r_inner=problem.r_inner,
        r_outer=problem.r_outer,
    )
    ranked = sorted(
        sector.choice_planet_ids,
        key=lambda planet_id: (
            _distance_to_mid(planet_id, problem, sector_mid),
            planet_id,
        ),
    )
    return tuple(ranked[:MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR])


def _distance_to_mid(
    planet_id: int,
    problem: LayoutPriorProblem,
    sector_mid: tuple[float, float],
) -> float:
    planet = problem.planets_by_id.get(planet_id)
    if planet is None:
        return float("inf")
    return distance_ly(planet.x, planet.y, sector_mid[0], sector_mid[1])
