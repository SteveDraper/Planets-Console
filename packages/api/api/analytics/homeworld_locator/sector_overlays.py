"""Homeworld circular sector ``regionOverlays`` (boundary + envelope disks).

Emits equal angular annular sectors when a viewpoint pin fixes ring rotation on
circular + round + epic|standard games. Observation completeness uses
planet-scan coverage from viewpoint + Share Intel origins.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from api.analytics.homeworld_locator.geometry import resolve_map_center
from api.analytics.homeworld_locator.layout_distributions_asset import (
    LayoutDistributionsAsset,
    load_default_layout_distributions_asset,
)
from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE
from api.analytics.homeworld_locator.types import HomeworldCandidateView
from api.analytics.turn_roster import players_by_id
from api.concepts.game_category import GameCategory
from api.concepts.homeworld_layout import (
    CLOSE_PLANETS_MAX_LY,
    VERY_CLOSE_PLANETS_MAX_LY,
    supports_circular_round_candidate_geometry,
)
from api.concepts.map_region_coverage import (
    CoverageOrigin,
    MapRegionBoundaryArcEdge,
    MapRegionBoundaryEdge,
    MapRegionBoundaryLineEdge,
    MapRegionOverlay,
    MapRegionOverlayDisk,
    MapRegionOverlayVertex,
    boundary_to_overlay,
    point_covered_by_origins,
)
from api.concepts.stellar_cartography.nebula_visibility import NebulaCenter, distance_ly
from api.concepts.visibility_coverage import planet_scan_origins, visibility_owner_ids
from api.concepts.warp_well import planet_is_planetoid
from api.models.game import TurnInfo
from api.models.planet import Planet

KIND_HOMEWORLD_SECTOR = "homeworld-sector"

STATUS_OK = "ok"
STATUS_INCOMPLETE = "incomplete"
STATUS_ERROR = "error"

HOVER_NO_CANDIDATES = "no candidates"

DEFAULT_SECTOR_FILL_COLOR = "#f97316"
# Keep sector fills light so base-map planets stay readable under the band.
DEFAULT_SECTOR_FILL_OPACITY = 0.08
ERROR_SECTOR_FILL_COLOR = "#ef4444"
ERROR_SECTOR_FILL_OPACITY = 0.12

# Observation sampling over the annular sector band.
_RADIAL_SAMPLE_STEP_LY = 10.0
_MIN_ANGLE_SAMPLES = 12

ENVELOPE_RADII_LY: tuple[float, float] = (
    VERY_CLOSE_PLANETS_MAX_LY,
    CLOSE_PLANETS_MAX_LY,
)


def homeworld_sector_emission_eligible(
    turn: TurnInfo,
    *,
    pin: Planet | None,
    player_count: int | None = None,
) -> bool:
    """True when Core should emit homeworld sector ``regionOverlays``."""
    if pin is None:
        return False
    resolved_count = player_count if player_count is not None else len(players_by_id(turn))
    if resolved_count < 2:
        return False
    if not supports_circular_round_candidate_geometry(turn.settings):
        return False
    category = GameCategory.from_game_settings(
        turn.settings,
        player_count=resolved_count,
    )
    return category in (GameCategory.EPIC, GameCategory.STANDARD)


def resolve_viewpoint_pin_planet(
    view: HomeworldCandidateView,
    planets: Sequence[Planet],
) -> Planet | None:
    """Viewpoint definite slot-anchored candidate planet, if present on the map."""
    planet_by_id = {planet.id: planet for planet in planets}
    for row in view.candidates:
        if row.confidence_tier != CONFIDENCE_DEFINITE:
            continue
        if row.perspective is None:
            continue
        planet = planet_by_id.get(row.planet_id)
        if planet is not None:
            return planet
    return None


def sector_index_for_angle(
    angle: float,
    *,
    pin_angle: float,
    player_count: int,
) -> int:
    """Sector index whose wedge is centered on ``pin_angle + k * 2π/n``."""
    half = math.pi / player_count
    delta = (angle - pin_angle) % (2.0 * math.pi)
    shifted = (delta + half) % (2.0 * math.pi)
    width = (2.0 * math.pi) / player_count
    return int(shifted / width) % player_count


def annular_sector_boundary(
    *,
    center: tuple[float, float],
    angle_start: float,
    angle_end: float,
    r_inner: float,
    r_outer: float,
) -> tuple[tuple[MapRegionOverlayVertex, ...], tuple[MapRegionBoundaryEdge, ...]]:
    """Closed annular-sector path: outer CCW arc, radial, inner CW arc, radial."""
    center_x, center_y = center
    outer_start = MapRegionOverlayVertex(
        x=center_x + r_outer * math.cos(angle_start),
        y=center_y + r_outer * math.sin(angle_start),
    )
    outer_end = MapRegionOverlayVertex(
        x=center_x + r_outer * math.cos(angle_end),
        y=center_y + r_outer * math.sin(angle_end),
    )
    inner_end = MapRegionOverlayVertex(
        x=center_x + r_inner * math.cos(angle_end),
        y=center_y + r_inner * math.sin(angle_end),
    )
    inner_start = MapRegionOverlayVertex(
        x=center_x + r_inner * math.cos(angle_start),
        y=center_y + r_inner * math.sin(angle_start),
    )
    vertices = (outer_start, outer_end, inner_end, inner_start)
    edges: tuple[MapRegionBoundaryEdge, ...] = (
        MapRegionBoundaryArcEdge(center_x=center_x, center_y=center_y, clockwise=False),
        MapRegionBoundaryLineEdge(),
        MapRegionBoundaryArcEdge(center_x=center_x, center_y=center_y, clockwise=True),
        MapRegionBoundaryLineEdge(),
    )
    return vertices, edges


def closest_unobserved_band_point(
    *,
    center: tuple[float, float],
    angle_start: float,
    angle_end: float,
    r_inner: float,
    r_outer: float,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
) -> tuple[float, float] | None:
    """Point in the annular sector closest to ``center`` that is not planet-scanned.

    Returns ``None`` when the sampled band is fully covered.
    """
    if not origins:
        # No scan origins → entire band unobserved; closest point is on the inner arc.
        mid = 0.5 * (angle_start + angle_end)
        return (
            center[0] + r_inner * math.cos(mid),
            center[1] + r_inner * math.sin(mid),
        )

    span = angle_end - angle_start
    if span <= 0:
        span += 2.0 * math.pi
    angle_samples = max(_MIN_ANGLE_SAMPLES, int(math.ceil(span / (math.pi / 36.0))))
    radial_steps = max(1, int(math.ceil((r_outer - r_inner) / _RADIAL_SAMPLE_STEP_LY)))

    best: tuple[float, float] | None = None
    best_dist = float("inf")
    for angle_index in range(angle_samples + 1):
        angle = angle_start + span * (angle_index / angle_samples)
        for radial_index in range(radial_steps + 1):
            radius = r_inner + (r_outer - r_inner) * (radial_index / radial_steps)
            x = center[0] + radius * math.cos(angle)
            y = center[1] + radius * math.sin(angle)
            if point_covered_by_origins(x, y, origins, nebulas):
                continue
            if radius < best_dist:
                best_dist = radius
                best = (x, y)
            # Further out on this ray is farther from C.
            break
    return best


def build_homeworld_sector_overlays(
    *,
    center: tuple[float, float],
    pin: Planet,
    player_count: int,
    r_inner: float,
    r_outer: float,
    planets: Sequence[Planet],
    candidate_planet_ids: frozenset[int],
    scan_origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter] = (),
) -> tuple[MapRegionOverlay, ...]:
    """Build one boundary overlay per equal angular sector."""
    if player_count < 2:
        return ()
    if r_outer < r_inner:
        raise ValueError("r_outer must be >= r_inner")

    center_x, center_y = center
    pin_angle = math.atan2(pin.y - center_y, pin.x - center_x)
    half = math.pi / player_count
    width = (2.0 * math.pi) / player_count

    # Candidates per sector: non-planetoid candidate planets in the annular wedge.
    candidates_by_sector: list[list[Planet]] = [[] for _ in range(player_count)]
    for planet in planets:
        if planet.id not in candidate_planet_ids:
            continue
        if planet_is_planetoid(planet):
            continue
        dist = distance_ly(planet.x, planet.y, center_x, center_y)
        if dist < r_inner or dist > r_outer:
            continue
        angle = math.atan2(planet.y - center_y, planet.x - center_x)
        index = sector_index_for_angle(angle, pin_angle=pin_angle, player_count=player_count)
        candidates_by_sector[index].append(planet)

    pin_sector = sector_index_for_angle(pin_angle, pin_angle=pin_angle, player_count=player_count)
    overlays: list[MapRegionOverlay] = []

    for index in range(player_count):
        angle_start = pin_angle + index * width - half
        angle_end = pin_angle + index * width + half
        is_viewpoint_sector = index == pin_sector
        sector_candidates = list(candidates_by_sector[index])
        # Viewpoint pin is always a candidate for its sector (may already be listed).
        if is_viewpoint_sector and all(planet.id != pin.id for planet in sector_candidates):
            sector_candidates.append(pin)

        unobserved = closest_unobserved_band_point(
            center=center,
            angle_start=angle_start,
            angle_end=angle_end,
            r_inner=r_inner,
            r_outer=r_outer,
            origins=scan_origins,
            nebulas=nebulas,
        )
        is_incomplete = unobserved is not None

        envelope_center: tuple[float, float] | None
        status: str
        hover: str
        fill_color = DEFAULT_SECTOR_FILL_COLOR
        fill_opacity = DEFAULT_SECTOR_FILL_OPACITY
        # Display-mode ``pinned`` / ``un-pinned``: sector has a planet candidate.
        has_candidate = len(sector_candidates) > 0

        if has_candidate:
            # Prefer a real candidate (closest to C) even when scan coverage is incomplete.
            # Viewpoint sector always centers on the pin planet.
            if is_viewpoint_sector:
                envelope_center = (float(pin.x), float(pin.y))
            else:
                closest = min(
                    sector_candidates,
                    key=lambda planet: distance_ly(planet.x, planet.y, center_x, center_y),
                )
                envelope_center = (float(closest.x), float(closest.y))
            status = STATUS_INCOMPLETE if is_incomplete else STATUS_OK
            hover = _hover_summary(
                is_viewpoint_sector=is_viewpoint_sector,
                candidate_count=len(sector_candidates),
                is_incomplete=is_incomplete,
                is_error=False,
            )
        elif is_incomplete:
            envelope_center = unobserved
            status = STATUS_INCOMPLETE
            hover = _hover_summary(
                is_viewpoint_sector=False,
                candidate_count=0,
                is_incomplete=True,
                is_error=False,
            )
        else:
            envelope_center = None
            status = STATUS_ERROR
            fill_color = ERROR_SECTOR_FILL_COLOR
            fill_opacity = ERROR_SECTOR_FILL_OPACITY
            hover = HOVER_NO_CANDIDATES

        disks: tuple[MapRegionOverlayDisk, ...] = ()
        if envelope_center is not None:
            ex, ey = envelope_center
            disks = tuple(
                MapRegionOverlayDisk(x=int(round(ex)), y=int(round(ey)), radius=radius)
                for radius in ENVELOPE_RADII_LY
            )

        vertices, edges = annular_sector_boundary(
            center=center,
            angle_start=angle_start,
            angle_end=angle_end,
            r_inner=r_inner,
            r_outer=r_outer,
        )
        overlays.append(
            boundary_to_overlay(
                kind=KIND_HOMEWORLD_SECTOR,
                overlay_id=f"homeworld-sector-{index}",
                fill_color=fill_color,
                fill_opacity=fill_opacity,
                vertices=vertices,
                edges=edges,
                disks=disks,
                is_pinned=has_candidate,
                status=status,
                hover_summary=hover,
            )
        )

    return tuple(overlays)


def build_homeworld_sector_overlays_for_turn(
    turn: TurnInfo,
    view: HomeworldCandidateView,
    *,
    layout_asset: LayoutDistributionsAsset | None = None,
    map_center: tuple[float, float] | None = None,
) -> tuple[MapRegionOverlay, ...]:
    """Emit sector overlays for a shell turn when the emission gate passes."""
    pin = resolve_viewpoint_pin_planet(view, turn.planets)
    player_count = len(players_by_id(turn))
    if pin is None or not homeworld_sector_emission_eligible(
        turn, pin=pin, player_count=player_count
    ):
        return ()

    category = GameCategory.from_game_settings(turn.settings, player_count=player_count)
    asset = layout_asset if layout_asset is not None else load_default_layout_distributions_asset()
    r_inner, r_outer = asset.center_distance_band(category)

    center = map_center if map_center is not None else resolve_map_center(turn.planets)
    owner_ids = visibility_owner_ids(turn.player.id, turn.relations)
    origins = planet_scan_origins(
        turn.planets,
        turn.ships,
        turn.hulls,
        owner_ids,
        planet_scan_range=float(turn.settings.planetscanrange),
    )
    candidate_ids = frozenset(row.planet_id for row in view.candidates)

    return build_homeworld_sector_overlays(
        center=center,
        pin=pin,
        player_count=player_count,
        r_inner=r_inner,
        r_outer=r_outer,
        planets=turn.planets,
        candidate_planet_ids=candidate_ids,
        scan_origins=origins,
        nebulas=turn.nebulas,
    )


def _hover_summary(
    *,
    is_viewpoint_sector: bool,
    candidate_count: int,
    is_incomplete: bool,
    is_error: bool,
) -> str:
    if is_error:
        return HOVER_NO_CANDIDATES
    parts: list[str] = []
    if is_viewpoint_sector:
        parts.append("viewpoint pin")
    if is_incomplete:
        parts.append("incomplete scan")
    parts.append("1 candidate" if candidate_count == 1 else f"{candidate_count} candidates")
    return " · ".join(parts)
