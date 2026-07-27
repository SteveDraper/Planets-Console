"""Homeworld circular sector ``regionOverlays`` (boundary + envelope disks).

Emits equal angular annular sectors when a viewpoint pin fixes ring rotation on
circular + round + epic|standard games. Observation completeness uses
planet-scan coverage from viewpoint + Share Intel origins.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from api.analytics.homeworld_locator.geometry import resolve_map_center, sector_index_for_angle
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
from api.errors import ValidationError
from api.models.game import GameInfo, TurnInfo
from api.models.planet import Planet
from api.models.player import Player, Race
from api.services.game_service import GameService

KIND_HOMEWORLD_SECTOR = "homeworld-sector"

STATUS_OK = "ok"
STATUS_INCOMPLETE = "incomplete"
STATUS_ERROR = "error"

# Wire ``fillColor`` / ``fillOpacity`` are required on shared overlays; sectors are
# stroke-only on the map (``fillOpacity`` always 0). Color marks ok vs error.
SECTOR_COLOR = "#f97316"
ERROR_SECTOR_COLOR = "#ef4444"

# Observation sampling over the annular sector band.
_RADIAL_SAMPLE_STEP_LY = 10.0
_MIN_ANGLE_SAMPLES = 12

ENVELOPE_RADII_LY: tuple[float, float] = (
    VERY_CLOSE_PLANETS_MAX_LY,
    CLOSE_PLANETS_MAX_LY,
)


def homeworld_layout_asset_category(
    turn: TurnInfo,
    *,
    player_count: int | None = None,
) -> GameCategory | None:
    """Return epic|standard when layout distribution asset tables apply; else None."""
    if not supports_circular_round_candidate_geometry(turn.settings):
        return None
    resolved_count = player_count if player_count is not None else len(players_by_id(turn))
    category = GameCategory.from_game_settings(
        turn.settings,
        player_count=resolved_count,
    )
    if category in (GameCategory.EPIC, GameCategory.STANDARD):
        return category
    return None


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
    return homeworld_layout_asset_category(turn, player_count=resolved_count) is not None


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


def _sector_angle_span(angle_start: float, angle_end: float) -> float:
    span = angle_end - angle_start
    if span <= 0:
        span += 2.0 * math.pi
    return span


def sector_band_geometric_center(
    *,
    center: tuple[float, float],
    angle_start: float,
    angle_end: float,
    r_inner: float,
    r_outer: float,
) -> tuple[float, float]:
    """Angular mid-ray at the midpoint radius of the annular sector."""
    mid_angle = angle_start + 0.5 * _sector_angle_span(angle_start, angle_end)
    mid_radius = 0.5 * (r_inner + r_outer)
    return (
        center[0] + mid_radius * math.cos(mid_angle),
        center[1] + mid_radius * math.sin(mid_angle),
    )


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

    On equal distance-to-C ties, prefer the sample nearest the sector mid-angle.
    Returns ``None`` when the sampled band is fully covered.
    """
    if not origins:
        # No scan origins → entire band unobserved; use geometric band center.
        return sector_band_geometric_center(
            center=center,
            angle_start=angle_start,
            angle_end=angle_end,
            r_inner=r_inner,
            r_outer=r_outer,
        )

    span = _sector_angle_span(angle_start, angle_end)
    mid_angle = angle_start + 0.5 * span
    angle_samples = max(_MIN_ANGLE_SAMPLES, int(math.ceil(span / (math.pi / 36.0))))
    radial_steps = max(1, int(math.ceil((r_outer - r_inner) / _RADIAL_SAMPLE_STEP_LY)))

    best: tuple[float, float] | None = None
    best_dist = float("inf")
    best_angle_delta = float("inf")
    for angle_index in range(angle_samples + 1):
        angle = angle_start + span * (angle_index / angle_samples)
        angle_delta = abs(angle - mid_angle)
        for radial_index in range(radial_steps + 1):
            radius = r_inner + (r_outer - r_inner) * (radial_index / radial_steps)
            x = center[0] + radius * math.cos(angle)
            y = center[1] + radius * math.sin(angle)
            if point_covered_by_origins(x, y, origins, nebulas):
                continue
            if radius < best_dist - 1e-9 or (
                abs(radius - best_dist) <= 1e-9 and angle_delta < best_angle_delta
            ):
                best_dist = radius
                best_angle_delta = angle_delta
                best = (x, y)
            # Further out on this ray is farther from C.
            break
    return best


@dataclass(frozen=True)
class _SectorOverlayDecision:
    """Per-sector status, envelope, color, and hover facts for one overlay emission."""

    is_pinned: bool
    envelope_center: tuple[float, float] | None
    status: str
    fill_color: str
    candidate_count: int
    player_label: str | None = None


def _planet_closest_to_sector_mid(
    planets: Sequence[Planet],
    *,
    center: tuple[float, float],
    angle_start: float,
    angle_end: float,
    r_inner: float,
    r_outer: float,
) -> Planet:
    """Candidate nearest the annular sector geometric center (mid-angle, mid-radius)."""
    sector_mid = sector_band_geometric_center(
        center=center,
        angle_start=angle_start,
        angle_end=angle_end,
        r_inner=r_inner,
        r_outer=r_outer,
    )
    return min(
        planets,
        key=lambda planet: distance_ly(planet.x, planet.y, sector_mid[0], sector_mid[1]),
    )


def _decide_sector_overlay(
    *,
    pin: Planet,
    is_viewpoint_sector: bool,
    sector_candidates: Sequence[Planet],
    slot_anchored: Sequence[Planet],
    is_incomplete: bool,
    center: tuple[float, float],
    angle_start: float,
    angle_end: float,
    r_inner: float,
    r_outer: float,
    label_by_planet: Mapping[int, str],
) -> _SectorOverlayDecision:
    """Pinned / orphan / incomplete / error → one decision for overlay emission."""
    is_pinned = len(slot_anchored) > 0
    candidate_count = len(sector_candidates)

    if is_pinned:
        # Slot-anchored: viewpoint pin in its sector, else closest to sector mid.
        if is_viewpoint_sector:
            anchor = pin
        else:
            anchor = _planet_closest_to_sector_mid(
                slot_anchored,
                center=center,
                angle_start=angle_start,
                angle_end=angle_end,
                r_inner=r_inner,
                r_outer=r_outer,
            )
        status = STATUS_INCOMPLETE if is_incomplete else STATUS_OK
        return _SectorOverlayDecision(
            is_pinned=True,
            envelope_center=(float(anchor.x), float(anchor.y)),
            status=status,
            fill_color=SECTOR_COLOR,
            candidate_count=candidate_count,
            player_label=label_by_planet.get(anchor.id),
        )

    if sector_candidates:
        # Orphans: envelope on candidate closest to sector mid (not map center C).
        closest = _planet_closest_to_sector_mid(
            sector_candidates,
            center=center,
            angle_start=angle_start,
            angle_end=angle_end,
            r_inner=r_inner,
            r_outer=r_outer,
        )
        status = STATUS_INCOMPLETE if is_incomplete else STATUS_OK
        return _SectorOverlayDecision(
            is_pinned=False,
            envelope_center=(float(closest.x), float(closest.y)),
            status=status,
            fill_color=SECTOR_COLOR,
            candidate_count=candidate_count,
        )

    if is_incomplete:
        # Fog placeholder: geometric band center (not closest-to-C sample).
        return _SectorOverlayDecision(
            is_pinned=False,
            envelope_center=sector_band_geometric_center(
                center=center,
                angle_start=angle_start,
                angle_end=angle_end,
                r_inner=r_inner,
                r_outer=r_outer,
            ),
            status=STATUS_INCOMPLETE,
            fill_color=SECTOR_COLOR,
            candidate_count=0,
        )

    return _SectorOverlayDecision(
        is_pinned=False,
        envelope_center=None,
        status=STATUS_ERROR,
        fill_color=ERROR_SECTOR_COLOR,
        candidate_count=0,
    )


def build_homeworld_sector_overlays(
    *,
    center: tuple[float, float],
    pin: Planet,
    player_count: int,
    r_inner: float,
    r_outer: float,
    planets: Sequence[Planet],
    candidate_planet_ids: frozenset[int],
    slot_anchored_planet_ids: frozenset[int],
    scan_origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter] = (),
    pinned_player_label_by_planet_id: Mapping[int, str] | None = None,
) -> tuple[MapRegionOverlay, ...]:
    """Build one boundary overlay per equal angular sector.

    ``is_pinned`` means the homeworld is determined and the owning player is
    known (a slot-anchored candidate planet lies in the sector). Orphan-only
    or empty sectors are un-pinned for display-mode filtering.

    ``pinned_player_label_by_planet_id`` maps slot-anchored planet ids to
    roster identity strings (``username (race)``) for wire ``playerLabel``.
    """
    if player_count < 2:
        return ()
    if r_outer < r_inner:
        raise ValueError("r_outer must be >= r_inner")

    label_by_planet = dict(pinned_player_label_by_planet_id or ())
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

        slot_anchored = [
            planet for planet in sector_candidates if planet.id in slot_anchored_planet_ids
        ]
        is_incomplete = (
            closest_unobserved_band_point(
                center=center,
                angle_start=angle_start,
                angle_end=angle_end,
                r_inner=r_inner,
                r_outer=r_outer,
                origins=scan_origins,
                nebulas=nebulas,
            )
            is not None
        )
        decision = _decide_sector_overlay(
            pin=pin,
            is_viewpoint_sector=is_viewpoint_sector,
            sector_candidates=sector_candidates,
            slot_anchored=slot_anchored,
            is_incomplete=is_incomplete,
            center=center,
            angle_start=angle_start,
            angle_end=angle_end,
            r_inner=r_inner,
            r_outer=r_outer,
            label_by_planet=label_by_planet,
        )

        disks: tuple[MapRegionOverlayDisk, ...] = ()
        if decision.envelope_center is not None:
            ex, ey = decision.envelope_center
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
                fill_color=decision.fill_color,
                fill_opacity=0.0,
                vertices=vertices,
                edges=edges,
                disks=disks,
                is_pinned=decision.is_pinned,
                status=decision.status,
                candidate_count=decision.candidate_count,
                player_label=decision.player_label,
            )
        )

    return tuple(overlays)


def build_homeworld_sector_overlays_for_turn(
    turn: TurnInfo,
    view: HomeworldCandidateView,
    *,
    layout_asset: LayoutDistributionsAsset | None = None,
    map_center: tuple[float, float] | None = None,
    shell_perspective: int | None = None,
    game_info: GameInfo | None = None,
    game_id: int | None = None,
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
    slot_anchored_ids = frozenset(
        row.planet_id for row in view.candidates if row.perspective is not None
    )
    resolved_game_id = game_id if game_id is not None else turn.settings.id
    labels = pinned_player_labels_for_view(
        turn,
        view,
        shell_perspective=shell_perspective,
        game_info=game_info,
        game_id=resolved_game_id,
    )

    return build_homeworld_sector_overlays(
        center=center,
        pin=pin,
        player_count=player_count,
        r_inner=r_inner,
        r_outer=r_outer,
        planets=turn.planets,
        candidate_planet_ids=candidate_ids,
        slot_anchored_planet_ids=slot_anchored_ids,
        scan_origins=origins,
        nebulas=turn.nebulas,
        pinned_player_label_by_planet_id=labels,
    )


def format_pinned_player_label(player: Player, races_by_id: Mapping[int, Race]) -> str:
    """Roster identity ``username (race name)`` for pinned-sector ``playerLabel``."""
    race = races_by_id.get(player.raceid)
    if race is not None and race.name:
        return f"{player.username} ({race.name})"
    return player.username


def player_for_homeworld_perspective(
    turn: TurnInfo,
    perspective: int,
    *,
    shell_perspective: int | None = None,
    game_info: GameInfo | None = None,
    game_id: int | None = None,
) -> Player | None:
    """Resolve a slot-anchored candidate perspective to a turn roster Player."""
    roster = players_by_id(turn)
    if game_info is not None and game_id is not None:
        try:
            player_id = GameService.player_id_for_perspective(game_info, perspective, game_id)
        except ValidationError:
            player_id = None
        if player_id is not None:
            player = roster.get(player_id)
            if player is not None:
                return player
    if shell_perspective is not None and perspective == shell_perspective:
        return turn.player
    return roster.get(perspective)


def pinned_player_labels_for_view(
    turn: TurnInfo,
    view: HomeworldCandidateView,
    *,
    shell_perspective: int | None = None,
    game_info: GameInfo | None = None,
    game_id: int | None = None,
) -> dict[int, str]:
    """Map slot-anchored candidate planet ids to roster identity labels."""
    races_by_id = {race.id: race for race in turn.races}
    labels: dict[int, str] = {}
    for row in view.candidates:
        if row.perspective is None:
            continue
        player = player_for_homeworld_perspective(
            turn,
            row.perspective,
            shell_perspective=shell_perspective,
            game_info=game_info,
            game_id=game_id,
        )
        if player is None:
            continue
        labels[row.planet_id] = format_pinned_player_label(player, races_by_id)
    return labels
