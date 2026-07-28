"""Shared layout-prior cost and position assembly (owned outside solvers)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from api.analytics.homeworld_locator.layout_distributions_asset import CategoryLayoutDistributions
from api.analytics.homeworld_locator.layout_prior_problem import SectorLayoutState
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.models.planet import Planet


def layout_prior_tie_key(chosen_by_sector: Mapping[int, int]) -> tuple[tuple[int, int], ...]:
    """Lexicographic tie-break key: sorted ``(sector_index, planet_id)`` pairs."""
    return tuple(sorted(chosen_by_sector.items()))


def positions_for_layout_prior_selection(
    *,
    chosen_by_sector: Mapping[int, int],
    fixed_by_sector: Mapping[int, SectorLayoutState],
    stand_in_sectors: Sequence[SectorLayoutState],
    planets_by_id: Mapping[int, Planet],
) -> dict[int, tuple[float, float]] | None:
    """Assemble ring positions for a discrete choice assignment.

    Stand-in positions use each stand-in sector's fixed mid placeholder.
    """
    positions: dict[int, tuple[float, float]] = {}
    for sector_index, state in fixed_by_sector.items():
        if state.fixed_position is not None:
            positions[sector_index] = state.fixed_position
    for sector_index, planet_id in chosen_by_sector.items():
        planet = planets_by_id.get(planet_id)
        if planet is None:
            return None
        positions[sector_index] = (float(planet.x), float(planet.y))

    for state in stand_in_sectors:
        if state.stand_in_position is None:
            return None
        positions[state.sector_index] = state.stand_in_position
    return positions


def layout_prior_cost(
    positions_by_sector: Mapping[int, tuple[float, float]],
    *,
    center: tuple[float, float],
    slot_anchored_sectors: frozenset[int],
    distributions: CategoryLayoutDistributions,
) -> float:
    """Equal-family layout-prior cost for a closed (or partial) ring of positions."""
    if len(positions_by_sector) < 2:
        return 0.0

    center_x, center_y = center
    ring = sorted(
        positions_by_sector.items(),
        key=lambda item: math.atan2(item[1][1] - center_y, item[1][0] - center_x),
        reverse=True,
    )

    neighbor_deviations: list[float] = []
    for index, (_, position) in enumerate(ring):
        next_position = ring[(index + 1) % len(ring)][1]
        separation = distance_ly(
            position[0],
            position[1],
            next_position[0],
            next_position[1],
        )
        percentile = distributions.neighbor_separation.percentile_for_value(separation)
        neighbor_deviations.append(abs(percentile - 50.0))
    neighbor_mean = sum(neighbor_deviations) / len(neighbor_deviations)

    center_deviations: list[float] = []
    for sector_index, position in positions_by_sector.items():
        if sector_index in slot_anchored_sectors:
            continue
        center_distance = distance_ly(position[0], position[1], center_x, center_y)
        percentile = distributions.center_distance.percentile_for_value(center_distance)
        center_deviations.append(abs(percentile - 50.0))
    center_mean = sum(center_deviations) / len(center_deviations) if center_deviations else 0.0
    return neighbor_mean + center_mean
