"""Shared homeworld-sector candidate partition (ownership + layout prior)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from api.analytics.homeworld_locator.geometry import resolve_map_center, sector_index_for_angle
from api.analytics.homeworld_locator.layout_distributions_asset import (
    LayoutDistributionsAsset,
    load_default_layout_distributions_asset,
)
from api.analytics.homeworld_locator.sector_overlays import (
    homeworld_layout_asset_category,
    homeworld_sector_emission_eligible,
    resolve_viewpoint_pin_planet,
    sector_band_geometric_center,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord, HomeworldCandidateView
from api.analytics.turn_roster import players_by_id
from api.concepts.game_category import GameCategory
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.concepts.warp_well import planet_is_planetoid
from api.models.game import TurnInfo
from api.models.planet import Planet


@dataclass(frozen=True)
class HomeworldSectorPartition:
    """Geometry and per-sector candidate buckets for one eligible shell turn."""

    center: tuple[float, float]
    pin: Planet
    player_count: int
    r_inner: float
    r_outer: float
    pin_angle: float
    width: float
    half: float
    candidates_by_sector: tuple[tuple[HomeworldCandidateRecord, ...], ...]
    candidate_planets_by_sector: tuple[tuple[Planet, ...], ...]
    sector_mids: tuple[tuple[float, float], ...]
    planet_sector_index: Mapping[int, int]


def partition_candidates_by_homeworld_sector(
    *,
    candidates: Sequence[HomeworldCandidateRecord],
    planets_by_id: Mapping[int, Planet],
    pin: Planet,
    pin_angle: float,
    player_count: int,
    center: tuple[float, float],
    r_inner: float,
    r_outer: float,
) -> tuple[
    tuple[tuple[HomeworldCandidateRecord, ...], ...],
    tuple[tuple[Planet, ...], ...],
    dict[int, int],
]:
    """Bucket traditional candidate planets into annular homeworld sectors.

    Viewpoint pin is forced into its sector when it is a candidate but outside
    the distance band (same rule as layout-prior / overlays).
    """
    center_x, center_y = center
    candidates_by_sector: list[list[HomeworldCandidateRecord]] = [[] for _ in range(player_count)]
    candidate_planets_by_sector: list[list[Planet]] = [[] for _ in range(player_count)]
    planet_sector_index: dict[int, int] = {}
    candidate_ids = {row.planet_id for row in candidates}

    for row in candidates:
        planet = planets_by_id.get(row.planet_id)
        if planet is None or planet_is_planetoid(planet):
            continue
        dist = distance_ly(planet.x, planet.y, center_x, center_y)
        if dist < r_inner or dist > r_outer:
            continue
        angle = math.atan2(planet.y - center_y, planet.x - center_x)
        index = sector_index_for_angle(angle, pin_angle=pin_angle, player_count=player_count)
        candidates_by_sector[index].append(row)
        candidate_planets_by_sector[index].append(planet)
        planet_sector_index[planet.id] = index

    pin_sector = sector_index_for_angle(pin_angle, pin_angle=pin_angle, player_count=player_count)
    if pin.id in candidate_ids and pin.id not in planet_sector_index:
        pin_row = next((row for row in candidates if row.planet_id == pin.id), None)
        if pin_row is not None:
            candidates_by_sector[pin_sector].append(pin_row)
            candidate_planets_by_sector[pin_sector].append(pin)
            planet_sector_index[pin.id] = pin_sector

    return (
        tuple(tuple(rows) for rows in candidates_by_sector),
        tuple(tuple(rows) for rows in candidate_planets_by_sector),
        planet_sector_index,
    )


def build_homeworld_sector_partition(
    turn: TurnInfo,
    *,
    candidates: Sequence[HomeworldCandidateRecord],
    baseline_turn: int,
    layout_asset: LayoutDistributionsAsset | None = None,
    shell_perspective: int | None = None,
    asserted_location_planet_ids: Sequence[int] = (),
) -> HomeworldSectorPartition | None:
    """Return sector partition when homeworld sector emission is eligible."""
    view = HomeworldCandidateView(
        candidates=tuple(candidates),
        baseline_turn=baseline_turn,
        baseline_degraded=False,
        available=True,
    )
    pin = resolve_viewpoint_pin_planet(
        view,
        turn.planets,
        shell_perspective=shell_perspective,
        asserted_location_planet_ids=asserted_location_planet_ids,
    )
    player_count = len(players_by_id(turn))
    if pin is None or not homeworld_sector_emission_eligible(
        turn,
        pin=pin,
        player_count=player_count,
    ):
        return None

    category = homeworld_layout_asset_category(turn, player_count=player_count)
    if category is None:
        return None
    asset = layout_asset if layout_asset is not None else load_default_layout_distributions_asset()
    game_category = GameCategory.from_game_settings(turn.settings, player_count=player_count)
    r_inner, r_outer = asset.center_distance_band(game_category)

    center = resolve_map_center(turn.planets)
    center_x, center_y = center
    pin_angle = math.atan2(pin.y - center_y, pin.x - center_x)
    half = math.pi / player_count
    width = (2.0 * math.pi) / player_count
    planets_by_id = {planet.id: planet for planet in turn.planets}

    candidates_by_sector, candidate_planets_by_sector, planet_sector_index = (
        partition_candidates_by_homeworld_sector(
            candidates=candidates,
            planets_by_id=planets_by_id,
            pin=pin,
            pin_angle=pin_angle,
            player_count=player_count,
            center=center,
            r_inner=r_inner,
            r_outer=r_outer,
        )
    )

    sector_mids: list[tuple[float, float]] = []
    for index in range(player_count):
        angle_start = pin_angle + index * width - half
        angle_end = pin_angle + index * width + half
        sector_mids.append(
            sector_band_geometric_center(
                center=center,
                angle_start=angle_start,
                angle_end=angle_end,
                r_inner=r_inner,
                r_outer=r_outer,
            )
        )

    return HomeworldSectorPartition(
        center=center,
        pin=pin,
        player_count=player_count,
        r_inner=r_inner,
        r_outer=r_outer,
        pin_angle=pin_angle,
        width=width,
        half=half,
        candidates_by_sector=candidates_by_sector,
        candidate_planets_by_sector=candidate_planets_by_sector,
        sector_mids=tuple(sector_mids),
        planet_sector_index=planet_sector_index,
    )
