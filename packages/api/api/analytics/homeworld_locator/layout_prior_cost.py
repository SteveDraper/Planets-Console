"""Shared layout-prior cost and position assembly (owned outside solvers)."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from api.analytics.homeworld_locator.layout_distributions_asset import CategoryLayoutDistributions
from api.analytics.homeworld_locator.layout_prior_problem import (
    LayoutPriorProblem,
    SectorLayoutState,
)
from api.analytics.homeworld_locator.models import OriginDistanceObservation
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.models.planet import Planet

# Floor for empty |S ∩ M| / |M| so -log stays finite.
ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS = 1e-12


@dataclass(frozen=True)
class NeighborEdgeContribution:
    """One clockwise-neighbor ring edge and its Normal ``-log`` density term."""

    from_sector: int
    to_sector: int
    separation_ly: float
    neg_log_density: float


@dataclass(frozen=True)
class CenterDistanceContribution:
    """One unpinned member's map-center distance term."""

    sector_index: int
    center_distance_ly: float
    neg_log_density: float


@dataclass(frozen=True)
class LayoutPriorCostBreakdown:
    """Full decomposition of :func:`layout_prior_cost` into family means and terms."""

    ring_sector_order: tuple[int, ...]
    neighbor_edges: tuple[NeighborEdgeContribution, ...]
    center_terms: tuple[CenterDistanceContribution, ...]
    neighbor_mean: float
    center_mean: float
    evidence_mean: float
    total: float


def layout_prior_tie_key(chosen_by_sector: Mapping[int, int]) -> tuple[tuple[int, int], ...]:
    """Lexicographic tie-break key: sorted ``(sector_index, planet_id)`` pairs."""
    return tuple(sorted(chosen_by_sector.items()))


def selection_planet_ids_for_layout_prior(
    *,
    fixed_by_sector: Mapping[int, SectorLayoutState],
    chosen_by_sector: Mapping[int, int],
) -> frozenset[int]:
    """Planet ids in selection S: fixed definites + choice assignments (not stand-ins)."""
    selected: set[int] = set()
    for state in fixed_by_sector.values():
        if state.fixed_planet_id is not None:
            selected.add(state.fixed_planet_id)
    selected.update(chosen_by_sector.values())
    return frozenset(selected)


def origin_distance_observation_neg_log(
    observation: OriginDistanceObservation,
    selection_planet_ids: frozenset[int],
    *,
    empty_intersection_eps: float = ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS,
) -> float:
    """``-log P(o|S)`` with ``P = |S ∩ M| / |M|`` (ε floor when empty)."""
    match_set = observation.matched_planet_ids
    if not match_set:
        return -math.log(empty_intersection_eps)
    overlap = sum(1 for planet_id in match_set if planet_id in selection_planet_ids)
    probability = max(empty_intersection_eps, overlap / len(match_set))
    return -math.log(probability)


def origin_distance_update_weight(turn: int, evidence_lambda: float) -> float:
    """Absolute-turn weight ``w(t) = λ^t`` for blending new evidence at turn ``t``.

    Empty turns do not call this: existing ``E`` is carried forward undiminished
    until a nonempty turn renormalizes with this weight (late turns → small ``w``).
    """
    if turn < 0:
        raise ValueError(f"origin-distance evidence turn must be >= 0, got {turn}")
    return evidence_lambda**turn


def origin_distance_evidence_mean(
    observations: Sequence[OriginDistanceObservation],
    selection_planet_ids: frozenset[int],
    *,
    evidence_lambda: float,
    empty_intersection_eps: float = ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS,
) -> float:
    """Soft evidence cost ``E(S)`` with absolute-turn update weights.

    Per turn with ≥1 observation: ``e_t = mean(-log P)``. Skip empty turns so
    ``E`` is unchanged when no new evidence arrives. On nonempty turn ``t``:
    ``E = (E + w(t) e_t) / (1 + w(t))`` with ``w(t) = λ^t``. No observations → ``0``.
    """
    if not observations:
        return 0.0

    by_turn: dict[int, list[OriginDistanceObservation]] = defaultdict(list)
    for observation in observations:
        by_turn[observation.turn].append(observation)

    evidence = 0.0
    for turn in sorted(by_turn):
        turn_obs = by_turn[turn]
        turn_mean = sum(
            origin_distance_observation_neg_log(
                observation,
                selection_planet_ids,
                empty_intersection_eps=empty_intersection_eps,
            )
            for observation in turn_obs
        ) / len(turn_obs)
        weight = origin_distance_update_weight(turn, evidence_lambda)
        evidence = (evidence + weight * turn_mean) / (1.0 + weight)
    return evidence


def positions_for_layout_prior_selection(
    *,
    chosen_by_sector: Mapping[int, int],
    fixed_by_sector: Mapping[int, SectorLayoutState],
    stand_in_sectors: Sequence[SectorLayoutState],
    planets_by_id: Mapping[int, Planet],
    stand_in_positions: Mapping[int, tuple[float, float]] | None = None,
) -> dict[int, tuple[float, float]] | None:
    """Assemble ring positions for a discrete choice assignment.

    When ``stand_in_positions`` is omitted, each stand-in sector uses its fixed
    mid placeholder. When provided, those coordinates override the mid.
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
        override = (
            None if stand_in_positions is None else stand_in_positions.get(state.sector_index)
        )
        if override is not None:
            positions[state.sector_index] = override
        elif state.stand_in_position is not None:
            positions[state.sector_index] = state.stand_in_position
        else:
            return None
    return positions


def layout_prior_cost_breakdown(
    positions_by_sector: Mapping[int, tuple[float, float]],
    *,
    center: tuple[float, float],
    slot_anchored_sectors: frozenset[int],
    distributions: CategoryLayoutDistributions,
    evidence_mean: float = 0.0,
) -> LayoutPriorCostBreakdown:
    """Decompose equal-family layout-prior cost into per-edge and per-member terms.

    Geometric families are means of Normal ``-log`` densities under the category
    asset tables (neighbor separation and center distance). Soft origin-distance
    evidence is an equal third family mean (``0`` when absent).
    """
    if len(positions_by_sector) < 2:
        return LayoutPriorCostBreakdown(
            ring_sector_order=tuple(sorted(positions_by_sector)),
            neighbor_edges=(),
            center_terms=(),
            neighbor_mean=0.0,
            center_mean=0.0,
            evidence_mean=evidence_mean,
            total=evidence_mean,
        )

    center_x, center_y = center
    ring = sorted(
        positions_by_sector.items(),
        key=lambda item: math.atan2(item[1][1] - center_y, item[1][0] - center_x),
        reverse=True,
    )

    neighbor_edges: list[NeighborEdgeContribution] = []
    for index, (sector_index, position) in enumerate(ring):
        next_sector, next_position = ring[(index + 1) % len(ring)]
        separation = distance_ly(
            position[0],
            position[1],
            next_position[0],
            next_position[1],
        )
        neighbor_edges.append(
            NeighborEdgeContribution(
                from_sector=sector_index,
                to_sector=next_sector,
                separation_ly=separation,
                neg_log_density=distributions.neighbor_separation.neg_log_density(separation),
            )
        )
    neighbor_mean = sum(edge.neg_log_density for edge in neighbor_edges) / len(neighbor_edges)

    center_terms: list[CenterDistanceContribution] = []
    for sector_index, position in positions_by_sector.items():
        if sector_index in slot_anchored_sectors:
            continue
        center_distance = distance_ly(position[0], position[1], center_x, center_y)
        center_terms.append(
            CenterDistanceContribution(
                sector_index=sector_index,
                center_distance_ly=center_distance,
                neg_log_density=distributions.center_distance.neg_log_density(center_distance),
            )
        )
    center_mean = (
        sum(term.neg_log_density for term in center_terms) / len(center_terms)
        if center_terms
        else 0.0
    )
    return LayoutPriorCostBreakdown(
        ring_sector_order=tuple(sector for sector, _ in ring),
        neighbor_edges=tuple(neighbor_edges),
        center_terms=tuple(center_terms),
        neighbor_mean=neighbor_mean,
        center_mean=center_mean,
        evidence_mean=evidence_mean,
        total=neighbor_mean + center_mean + evidence_mean,
    )


def layout_prior_cost(
    positions_by_sector: Mapping[int, tuple[float, float]],
    *,
    center: tuple[float, float],
    slot_anchored_sectors: frozenset[int],
    distributions: CategoryLayoutDistributions,
    evidence_mean: float = 0.0,
) -> float:
    """Equal-family layout-prior cost for a closed (or partial) ring of positions."""
    return layout_prior_cost_breakdown(
        positions_by_sector,
        center=center,
        slot_anchored_sectors=slot_anchored_sectors,
        distributions=distributions,
        evidence_mean=evidence_mean,
    ).total


def fixed_and_slot_anchored(
    sector_states: Sequence[SectorLayoutState],
) -> tuple[dict[int, SectorLayoutState], frozenset[int]]:
    """Fixed sectors keyed by index, plus the slot-anchored sector index set."""
    fixed_by_sector = {
        state.sector_index: state
        for state in sector_states
        if state.kind == "fixed" and state.fixed_position is not None
    }
    slot_anchored = frozenset(
        state.sector_index for state in fixed_by_sector.values() if state.is_slot_anchored
    )
    return fixed_by_sector, slot_anchored


def mid_stand_in_positions(
    stand_in_sectors: Sequence[SectorLayoutState],
) -> dict[int, tuple[float, float]]:
    """Fixed mid placeholders for stand-in sectors (used during discrete search)."""
    return {
        state.sector_index: state.stand_in_position
        for state in stand_in_sectors
        if state.stand_in_position is not None
    }


def evaluate_layout_prior_selection(
    problem: LayoutPriorProblem,
    chosen_by_sector: Mapping[int, int],
    *,
    stand_in_positions: Mapping[int, tuple[float, float]] | None = None,
) -> tuple[float, tuple[tuple[int, int], ...]] | None:
    """Score a discrete assignment; ``None`` when positions cannot be assembled."""
    breakdown = evaluate_layout_prior_selection_breakdown(
        problem, chosen_by_sector, stand_in_positions=stand_in_positions
    )
    if breakdown is None:
        return None
    return breakdown[0].total, breakdown[1]


def evaluate_layout_prior_selection_breakdown(
    problem: LayoutPriorProblem,
    chosen_by_sector: Mapping[int, int],
    *,
    stand_in_positions: Mapping[int, tuple[float, float]] | None = None,
) -> tuple[LayoutPriorCostBreakdown, tuple[tuple[int, int], ...]] | None:
    """Score a discrete assignment with full cost decomposition."""
    fixed_by_sector, slot_anchored = fixed_and_slot_anchored(problem.sector_states)
    stand_in_sectors = [state for state in problem.sector_states if state.kind == "stand_in"]
    positions = positions_for_layout_prior_selection(
        chosen_by_sector=chosen_by_sector,
        fixed_by_sector=fixed_by_sector,
        stand_in_sectors=stand_in_sectors,
        planets_by_id=problem.planets_by_id,
        stand_in_positions=stand_in_positions,
    )
    if positions is None:
        return None
    selection_ids = selection_planet_ids_for_layout_prior(
        fixed_by_sector=fixed_by_sector,
        chosen_by_sector=chosen_by_sector,
    )
    evidence_mean = origin_distance_evidence_mean(
        problem.origin_distance_observations,
        selection_ids,
        evidence_lambda=problem.origin_distance_evidence_lambda,
    )
    breakdown = layout_prior_cost_breakdown(
        positions,
        center=problem.center,
        slot_anchored_sectors=slot_anchored,
        distributions=problem.distributions,
        evidence_mean=evidence_mean,
    )
    return breakdown, layout_prior_tie_key(chosen_by_sector)
