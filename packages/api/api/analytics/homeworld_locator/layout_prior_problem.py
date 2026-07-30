"""Layout-prior problem state: sector participation built outside solvers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from api.analytics.homeworld_locator.geometry import sector_index_for_angle
from api.analytics.homeworld_locator.layout_distributions_asset import CategoryLayoutDistributions
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    OriginDistanceObservation,
)
from api.analytics.homeworld_locator.sector_overlays import (
    sector_band_geometric_center,
    unobserved_band_sample_points,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord
from api.concepts.map_region_coverage import CoverageOrigin
from api.concepts.stellar_cartography.nebula_visibility import NebulaCenter, distance_ly
from api.concepts.warp_well import planet_is_planetoid
from api.models.planet import Planet

SectorKind = Literal["fixed", "choice", "stand_in", "skip"]


@dataclass(frozen=True)
class SectorLayoutState:
    """Per-sector participation for layout-prior selection."""

    sector_index: int
    kind: SectorKind
    angle_start: float
    angle_end: float
    fixed_position: tuple[float, float] | None = None
    fixed_planet_id: int | None = None
    is_slot_anchored: bool = False
    # All legal possibles for choice sectors (solvers may further restrict).
    choice_planet_ids: tuple[int, ...] = ()
    # Fixed mid stand-in placeholder for empty unobserved sectors.
    stand_in_position: tuple[float, float] | None = None
    # Full unobserved sample grid (stand-in sectors only; used by refine).
    stand_in_samples: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class LayoutPriorProblem:
    """Solver-facing layout-prior instance (sector ring + scoring context)."""

    sector_states: tuple[SectorLayoutState, ...]
    planets_by_id: Mapping[int, Planet]
    center: tuple[float, float]
    r_inner: float
    r_outer: float
    distributions: CategoryLayoutDistributions
    # Soft origin-distance evidence blend weight base (``w(t)=λ^t``). Required:
    # the only default lives on ``HomeworldLocatorConfig``, so callers resolve it.
    origin_distance_evidence_lambda: float
    # Seed materials for deterministic anneal (shell scope + input fingerprint).
    seed_game_id: int = 0
    seed_turn: int = 0
    seed_perspective: int = 0
    seed_input_fingerprint: tuple[tuple[int, str, int | None], ...] = ()
    # When set, anneal RNG hashes this turn instead of ``seed_turn`` (report turn
    # stays ``seed_turn``). Used by prev-seed + this-seed continuity solves.
    rng_seed_turn: int | None = None
    # Layout distribution category key (epic|standard) for telemetry / cooling analysis.
    layout_category: str | None = None
    # Soft origin-distance evidence (equal third cost family).
    origin_distance_observations: tuple[OriginDistanceObservation, ...] = ()


def build_sector_layout_states(
    *,
    candidates: Sequence[HomeworldCandidateRecord],
    planets_by_id: Mapping[int, Planet],
    pin: Planet,
    pin_angle: float,
    player_count: int,
    center: tuple[float, float],
    r_inner: float,
    r_outer: float,
    half: float,
    width: float,
    scan_origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
) -> tuple[SectorLayoutState, ...]:
    """Classify each homeworld sector as fixed, choice, stand-in, or skip."""
    center_x, center_y = center
    pin_sector = sector_index_for_angle(pin_angle, pin_angle=pin_angle, player_count=player_count)

    candidates_by_sector: list[list[tuple[HomeworldCandidateRecord, Planet]]] = [
        [] for _ in range(player_count)
    ]
    for row in candidates:
        planet = planets_by_id.get(row.planet_id)
        if planet is None or planet_is_planetoid(planet):
            continue
        dist = distance_ly(planet.x, planet.y, center_x, center_y)
        if dist < r_inner or dist > r_outer:
            continue
        angle = math.atan2(planet.y - center_y, planet.x - center_x)
        index = sector_index_for_angle(angle, pin_angle=pin_angle, player_count=player_count)
        candidates_by_sector[index].append((row, planet))

    if all(planet.id != pin.id for _, planet in candidates_by_sector[pin_sector]):
        pin_planet = planets_by_id.get(pin.id)
        if pin_planet is not None:
            for row in candidates:
                if row.planet_id == pin.id:
                    candidates_by_sector[pin_sector].append((row, pin_planet))
                    break

    states: list[SectorLayoutState] = []
    for index in range(player_count):
        angle_start = pin_angle + index * width - half
        angle_end = pin_angle + index * width + half
        sector_rows = candidates_by_sector[index]

        slot_definite: tuple[HomeworldCandidateRecord, Planet] | None = None
        orphan_definite: tuple[HomeworldCandidateRecord, Planet] | None = None
        possibles: list[tuple[HomeworldCandidateRecord, Planet]] = []
        for row, planet in sector_rows:
            if row.confidence_tier == CONFIDENCE_DEFINITE:
                if row.perspective is not None:
                    slot_definite = (row, planet)
                else:
                    orphan_definite = (row, planet)
            elif row.confidence_tier == CONFIDENCE_POSSIBLE:
                possibles.append((row, planet))

        if slot_definite is not None:
            row, planet = slot_definite
            states.append(
                SectorLayoutState(
                    sector_index=index,
                    kind="fixed",
                    angle_start=angle_start,
                    angle_end=angle_end,
                    fixed_position=(float(planet.x), float(planet.y)),
                    fixed_planet_id=row.planet_id,
                    is_slot_anchored=True,
                )
            )
            continue

        if orphan_definite is not None:
            row, planet = orphan_definite
            states.append(
                SectorLayoutState(
                    sector_index=index,
                    kind="fixed",
                    angle_start=angle_start,
                    angle_end=angle_end,
                    fixed_position=(float(planet.x), float(planet.y)),
                    fixed_planet_id=row.planet_id,
                    is_slot_anchored=False,
                )
            )
            continue

        if possibles:
            by_planet_id: dict[int, Planet] = {}
            for row, planet in possibles:
                by_planet_id.setdefault(row.planet_id, planet)
            choice_ids = tuple(sorted(by_planet_id))
            states.append(
                SectorLayoutState(
                    sector_index=index,
                    kind="choice",
                    angle_start=angle_start,
                    angle_end=angle_end,
                    choice_planet_ids=choice_ids,
                )
            )
            continue

        samples = unobserved_band_sample_points(
            center=center,
            angle_start=angle_start,
            angle_end=angle_end,
            r_inner=r_inner,
            r_outer=r_outer,
            origins=scan_origins,
            nebulas=nebulas,
        )
        if samples:
            sector_mid = sector_band_geometric_center(
                center=center,
                angle_start=angle_start,
                angle_end=angle_end,
                r_inner=r_inner,
                r_outer=r_outer,
            )
            stand_in = min(
                samples,
                key=lambda point: distance_ly(point[0], point[1], sector_mid[0], sector_mid[1]),
            )
            states.append(
                SectorLayoutState(
                    sector_index=index,
                    kind="stand_in",
                    angle_start=angle_start,
                    angle_end=angle_end,
                    stand_in_position=stand_in,
                    stand_in_samples=samples,
                )
            )
        else:
            states.append(
                SectorLayoutState(
                    sector_index=index,
                    kind="skip",
                    angle_start=angle_start,
                    angle_end=angle_end,
                )
            )

    return tuple(states)


def build_layout_prior_problem(
    *,
    candidates: Sequence[HomeworldCandidateRecord],
    planets_by_id: Mapping[int, Planet],
    pin: Planet,
    pin_angle: float,
    player_count: int,
    center: tuple[float, float],
    r_inner: float,
    r_outer: float,
    half: float,
    width: float,
    scan_origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    distributions: CategoryLayoutDistributions,
    origin_distance_evidence_lambda: float,
    seed_game_id: int = 0,
    seed_turn: int = 0,
    seed_perspective: int = 0,
    seed_input_fingerprint: tuple[tuple[int, str, int | None], ...] = (),
    layout_category: str | None = None,
    origin_distance_observations: Sequence[OriginDistanceObservation] = (),
) -> LayoutPriorProblem:
    """Build the solver-facing problem from candidates and map geometry."""
    return LayoutPriorProblem(
        sector_states=build_sector_layout_states(
            candidates=candidates,
            planets_by_id=planets_by_id,
            pin=pin,
            pin_angle=pin_angle,
            player_count=player_count,
            center=center,
            r_inner=r_inner,
            r_outer=r_outer,
            half=half,
            width=width,
            scan_origins=scan_origins,
            nebulas=nebulas,
        ),
        planets_by_id=planets_by_id,
        center=center,
        r_inner=r_inner,
        r_outer=r_outer,
        distributions=distributions,
        seed_game_id=seed_game_id,
        seed_turn=seed_turn,
        seed_perspective=seed_perspective,
        seed_input_fingerprint=seed_input_fingerprint,
        layout_category=layout_category,
        origin_distance_observations=tuple(origin_distance_observations),
        origin_distance_evidence_lambda=origin_distance_evidence_lambda,
    )
