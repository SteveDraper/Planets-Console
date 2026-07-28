"""Sample-grid stand-in refine for layout-prior solutions (#270 / #273 hook)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from api.analytics.homeworld_locator.layout_prior_cost import (
    fixed_and_slot_anchored,
    layout_prior_cost,
    mid_stand_in_positions,
    positions_for_layout_prior_selection,
)
from api.analytics.homeworld_locator.layout_prior_problem import LayoutPriorProblem

# Safety cap on full alternating sweeps (outside the SA stop-gate).
MAX_STAND_IN_REFINE_SWEEPS = 64


class StandInSampleScorer(Protocol):
    """Score one stand-in sample for a sector given the rest of the ring.

    Default is layout-prior cost only. #273 may supply a launch-consistency
    term via a custom scorer without changing the sample grid.
    """

    def __call__(
        self,
        *,
        sector_index: int,
        sample: tuple[float, float],
        positions_by_sector: Mapping[int, tuple[float, float]],
        problem: LayoutPriorProblem,
        slot_anchored_sectors: frozenset[int],
    ) -> float: ...


def layout_cost_stand_in_sample_scorer(
    *,
    sector_index: int,
    sample: tuple[float, float],
    positions_by_sector: Mapping[int, tuple[float, float]],
    problem: LayoutPriorProblem,
    slot_anchored_sectors: frozenset[int],
) -> float:
    """Default #270 scorer: substitute ``sample`` and evaluate layout-prior cost."""
    trial = dict(positions_by_sector)
    trial[sector_index] = sample
    return layout_prior_cost(
        trial,
        center=problem.center,
        slot_anchored_sectors=slot_anchored_sectors,
        distributions=problem.distributions,
    )


def refine_stand_in_positions(
    problem: LayoutPriorProblem,
    chosen_by_sector: Mapping[int, int],
    *,
    initial_stand_in_positions: Mapping[int, tuple[float, float]] | None = None,
    sample_scorer: StandInSampleScorer | Callable[..., float] | None = None,
    max_sweeps: int = MAX_STAND_IN_REFINE_SWEEPS,
) -> dict[int, tuple[float, float]]:
    """Alternating coordinate descent over stand-in sample grids.

    Sweeps stand-in sectors in ascending sector-index order until a full sweep
    makes no change or ``max_sweeps`` is reached. Discrete choices stay fixed.
    """
    stand_in_sectors = sorted(
        (state for state in problem.sector_states if state.kind == "stand_in"),
        key=lambda state: state.sector_index,
    )
    if not stand_in_sectors:
        return {}

    scorer: StandInSampleScorer = (
        layout_cost_stand_in_sample_scorer if sample_scorer is None else sample_scorer
    )
    fixed_by_sector, slot_anchored = fixed_and_slot_anchored(problem.sector_states)
    current: dict[int, tuple[float, float]] = dict(
        initial_stand_in_positions
        if initial_stand_in_positions is not None
        else mid_stand_in_positions(stand_in_sectors)
    )

    for _ in range(max_sweeps):
        changed = False
        for state in stand_in_sectors:
            samples = state.stand_in_samples
            if not samples:
                continue
            base_positions = positions_for_layout_prior_selection(
                chosen_by_sector=chosen_by_sector,
                fixed_by_sector=fixed_by_sector,
                stand_in_sectors=stand_in_sectors,
                planets_by_id=problem.planets_by_id,
                stand_in_positions=current,
            )
            if base_positions is None:
                continue
            best_sample = current.get(state.sector_index)
            best_score = float("inf")
            if best_sample is not None:
                best_score = scorer(
                    sector_index=state.sector_index,
                    sample=best_sample,
                    positions_by_sector=base_positions,
                    problem=problem,
                    slot_anchored_sectors=slot_anchored,
                )
            for sample in samples:
                score = scorer(
                    sector_index=state.sector_index,
                    sample=sample,
                    positions_by_sector=base_positions,
                    problem=problem,
                    slot_anchored_sectors=slot_anchored,
                )
                if score < best_score - 1e-12 or (
                    abs(score - best_score) <= 1e-12
                    and (best_sample is None or sample < best_sample)
                ):
                    best_score = score
                    best_sample = sample
            if best_sample is not None and current.get(state.sector_index) != best_sample:
                current[state.sector_index] = best_sample
                changed = True
        if not changed:
            break

    return current
