"""Homeworld layout prior selection and most-probable annotation (#36 phase 3)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import product
from typing import Literal

from api.analytics.homeworld_locator.geometry import resolve_map_center, sector_index_for_angle
from api.analytics.homeworld_locator.layout_distributions_asset import (
    CategoryLayoutDistributions,
    LayoutDistributionsAsset,
    load_default_layout_distributions_asset,
)
from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE
from api.analytics.homeworld_locator.sector_overlays import (
    homeworld_layout_asset_category,
    homeworld_sector_emission_eligible,
    resolve_viewpoint_pin_planet,
    unobserved_band_sample_points,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord, HomeworldCandidateView
from api.analytics.turn_roster import players_by_id
from api.concepts.map_region_coverage import CoverageOrigin
from api.concepts.stellar_cartography.nebula_visibility import NebulaCenter, distance_ly
from api.concepts.visibility_coverage import planet_scan_origins, visibility_owner_ids
from api.concepts.warp_well import planet_is_planetoid
from api.models.game import TurnInfo
from api.models.planet import Planet

_SectorKind = Literal["fixed", "choice", "stand_in", "skip"]


@dataclass(frozen=True)
class _SectorLayoutState:
    sector_index: int
    kind: _SectorKind
    angle_start: float
    angle_end: float
    fixed_position: tuple[float, float] | None = None
    fixed_planet_id: int | None = None
    is_slot_anchored: bool = False
    choice_planet_ids: tuple[int, ...] = ()
    stand_in_samples: tuple[tuple[float, float], ...] = ()


def apply_layout_prior_most_probable(
    candidates: Sequence[HomeworldCandidateRecord],
    *,
    turn: TurnInfo,
    view: HomeworldCandidateView,
    player_count: int | None = None,
    layout_asset: LayoutDistributionsAsset | None = None,
    map_center: tuple[float, float] | None = None,
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

    sector_states = _build_sector_states(
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
    )

    most_probable_ids = _select_most_probable_planet_ids(
        sector_states,
        planets_by_id=planets_by_id,
        center=center,
        distributions=distributions,
    )
    return tuple(
        replace(row, is_most_probable=row.planet_id in most_probable_ids)
        for row in candidates
    )


def _build_sector_states(
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
) -> tuple[_SectorLayoutState, ...]:
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

    states: list[_SectorLayoutState] = []
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
                _SectorLayoutState(
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
                _SectorLayoutState(
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
            choice_ids = tuple(sorted({row.planet_id for row, _ in possibles}))
            states.append(
                _SectorLayoutState(
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
            states.append(
                _SectorLayoutState(
                    sector_index=index,
                    kind="stand_in",
                    angle_start=angle_start,
                    angle_end=angle_end,
                    stand_in_samples=samples,
                )
            )
        else:
            states.append(
                _SectorLayoutState(
                    sector_index=index,
                    kind="skip",
                    angle_start=angle_start,
                    angle_end=angle_end,
                )
            )

    return tuple(states)


def _select_most_probable_planet_ids(
    sector_states: Sequence[_SectorLayoutState],
    *,
    planets_by_id: Mapping[int, Planet],
    center: tuple[float, float],
    distributions: CategoryLayoutDistributions,
) -> frozenset[int]:
    choice_sectors = [state for state in sector_states if state.kind == "choice"]
    if not choice_sectors:
        return frozenset()

    stand_in_sectors = [state for state in sector_states if state.kind == "stand_in"]
    fixed_by_sector = {
        state.sector_index: state
        for state in sector_states
        if state.kind == "fixed" and state.fixed_position is not None
    }

    choice_options = [sector.choice_planet_ids for sector in choice_sectors]
    best_cost = float("inf")
    best_tie_key: tuple[tuple[int, int], ...] = ()
    best_choices: dict[int, int] = {}

    for combo in product(*choice_options):
        chosen_by_sector = {
            sector.sector_index: planet_id
            for sector, planet_id in zip(choice_sectors, combo, strict=True)
        }
        positions = _positions_for_selection(
            chosen_by_sector=chosen_by_sector,
            fixed_by_sector=fixed_by_sector,
            stand_in_sectors=stand_in_sectors,
            planets_by_id=planets_by_id,
            center=center,
            distributions=distributions,
        )
        if positions is None:
            continue
        cost = _layout_prior_cost(
            positions,
            center=center,
            slot_anchored_sectors=frozenset(
                state.sector_index for state in fixed_by_sector.values() if state.is_slot_anchored
            ),
            distributions=distributions,
        )
        tie_key = tuple(sorted(chosen_by_sector.items()))
        if cost < best_cost - 1e-12 or (
            abs(cost - best_cost) <= 1e-12 and tie_key < best_tie_key
        ):
            best_cost = cost
            best_tie_key = tie_key
            best_choices = chosen_by_sector

    return frozenset(best_choices.values())


def _positions_for_selection(
    *,
    chosen_by_sector: Mapping[int, int],
    fixed_by_sector: Mapping[int, _SectorLayoutState],
    stand_in_sectors: Sequence[_SectorLayoutState],
    planets_by_id: Mapping[int, Planet],
    center: tuple[float, float],
    distributions: CategoryLayoutDistributions,
) -> dict[int, tuple[float, float]] | None:
    positions: dict[int, tuple[float, float]] = {}
    for sector_index, state in fixed_by_sector.items():
        if state.fixed_position is not None:
            positions[sector_index] = state.fixed_position
    for sector_index, planet_id in chosen_by_sector.items():
        planet = planets_by_id.get(planet_id)
        if planet is None:
            return None
        positions[sector_index] = (float(planet.x), float(planet.y))

    if not stand_in_sectors:
        return positions

    stand_in_indices = [state.sector_index for state in stand_in_sectors]
    samples_by_sector = {
        state.sector_index: state.stand_in_samples for state in stand_in_sectors
    }
    current = {
        sector: samples_by_sector[sector][0]
        for sector in stand_in_indices
        if samples_by_sector[sector]
    }
    if len(current) != len(stand_in_indices):
        return None

    improved = True
    while improved:
        improved = False
        for sector in stand_in_indices:
            best_point = current[sector]
            best_cost = _layout_prior_cost(
                {**positions, **current, sector: best_point},
                center=center,
                slot_anchored_sectors=frozenset(
                    index
                    for index, state in fixed_by_sector.items()
                    if state.is_slot_anchored
                ),
                distributions=distributions,
            )
            for point in samples_by_sector[sector]:
                trial = {**positions, **current, sector: point}
                cost = _layout_prior_cost(
                    trial,
                    center=center,
                    slot_anchored_sectors=frozenset(
                        index
                        for index, state in fixed_by_sector.items()
                        if state.is_slot_anchored
                    ),
                    distributions=distributions,
                )
                if cost < best_cost - 1e-12:
                    best_cost = cost
                    best_point = point
                    improved = True
            current[sector] = best_point

    positions.update(current)
    return positions


def _layout_prior_cost(
    positions_by_sector: Mapping[int, tuple[float, float]],
    *,
    center: tuple[float, float],
    slot_anchored_sectors: frozenset[int],
    distributions: CategoryLayoutDistributions,
) -> float:
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
    center_mean = (
        sum(center_deviations) / len(center_deviations) if center_deviations else 0.0
    )
    return neighbor_mean + center_mean
