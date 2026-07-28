"""Homeworld layout prior selection facade (#36 / #270).

Eligibility, sector build, cost ownership, and annotate stay here (or in sibling
shared modules). Discrete search is delegated to a replaceable ``LayoutPriorSolver``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from api.analytics.homeworld_locator.geometry import resolve_map_center
from api.analytics.homeworld_locator.layout_distributions_asset import (
    LayoutDistributionsAsset,
    load_default_layout_distributions_asset,
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
from api.analytics.homeworld_locator.layout_prior_solver import (
    LAYOUT_PRIOR_SOLVER_ENUMERATE,
    LayoutPriorSolution,
    LayoutPriorSolver,
    layout_prior_solver_from_config,
    layout_prior_solver_from_name,
)
from api.analytics.homeworld_locator.layout_prior_stop_gate import NeverStopGate
from api.analytics.homeworld_locator.sector_overlays import (
    homeworld_layout_asset_category,
    homeworld_sector_emission_eligible,
    resolve_viewpoint_pin_planet,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord, HomeworldCandidateView
from api.analytics.turn_roster import players_by_id
from api.concepts.visibility_coverage import planet_scan_origins, visibility_owner_ids
from api.models.game import TurnInfo

__all__ = [
    "LAYOUT_PRIOR_SOLVER_ENUMERATE",
    "MAX_LAYOUT_PRIOR_CHOICES_PER_SECTOR",
    "LayoutPriorProblem",
    "LayoutPriorSolution",
    "LayoutPriorSolver",
    "SectorLayoutState",
    "apply_layout_prior_most_probable",
    "build_sector_layout_states",
    "layout_prior_input_fingerprint",
    "layout_prior_solver_from_config",
    "layout_prior_solver_from_name",
]


def layout_prior_input_fingerprint(
    candidates: Sequence[HomeworldCandidateRecord],
) -> tuple[tuple[int, str, int | None], ...]:
    """Stable fingerprint of the post-promote/cull set that feeds selection."""
    return tuple(
        sorted((row.planet_id, row.confidence_tier, row.perspective) for row in candidates)
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
) -> tuple[HomeworldCandidateRecord, ...]:
    """Annotate ``is_most_probable`` after evidence culls when the emission gate passes."""
    resolved_count = player_count if player_count is not None else len(players_by_id(turn))
    pin = resolve_viewpoint_pin_planet(view, turn.planets)
    if pin is None or not homeworld_sector_emission_eligible(
        turn, pin=pin, player_count=resolved_count
    ):
        return tuple(
            replace(row, is_most_probable=False) if row.is_most_probable else row
            for row in candidates
        )

    category = homeworld_layout_asset_category(turn, player_count=resolved_count)
    if category is None:
        return tuple(candidates)

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

    problem = build_layout_prior_problem(
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
    )

    resolved_solver = solver if solver is not None else layout_prior_solver_from_config()
    solution = resolved_solver.solve(problem, stop_gate=NeverStopGate())
    most_probable_ids = frozenset(solution.chosen_planet_ids_by_sector.values())
    return tuple(
        replace(row, is_most_probable=row.planet_id in most_probable_ids) for row in candidates
    )
