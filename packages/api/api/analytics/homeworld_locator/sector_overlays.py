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
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    OwnershipProvenance,
    SectorOwnerMember,
)
from api.analytics.homeworld_locator.ownership_projection import (
    SectorOwnerOverlayProjection,
    project_sector_owner_sets_with_location_pins,
    unique_projected_owner_slot,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateView
from api.analytics.turn_roster import players_by_id, race_id_by_owner_slot
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
    MapRegionPossibleOwner,
    annulus_angle_span,
    annulus_polar_sample_counts,
    boundary_to_overlay,
    iter_annulus_polar_sample_points,
    point_covered_by_origins,
)
from api.concepts.stellar_cartography.nebula_visibility import NebulaCenter, distance_ly
from api.concepts.visibility_coverage import planet_scan_origins, visibility_owner_ids
from api.concepts.warp_well import planet_is_planetoid
from api.config import get_config
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

ENVELOPE_RADII_LY: tuple[float, float] = (
    VERY_CLOSE_PLANETS_MAX_LY,
    CLOSE_PLANETS_MAX_LY,
)


def envelope_disks_at(x: float, y: float) -> tuple[MapRegionOverlayDisk, ...]:
    """81/162 LY envelope disks centered on ``(x, y)`` (rounded to int ly)."""
    ix, iy = int(round(x)), int(round(y))
    return tuple(MapRegionOverlayDisk(x=ix, y=iy, radius=radius) for radius in ENVELOPE_RADII_LY)


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


def homeworld_sector_geometry_eligible(
    turn: TurnInfo,
    *,
    player_count: int | None = None,
) -> bool:
    """True when circular sector geometry applies (no viewpoint pin required).

    Gates on at least two players plus an epic|standard layout asset category
    (circular + round). Ownership API keying and overlay emission both use this;
    emission additionally requires a resolved pin.
    """
    resolved_count = player_count if player_count is not None else len(players_by_id(turn))
    if resolved_count < 2:
        return False
    return homeworld_layout_asset_category(turn, player_count=resolved_count) is not None


def homeworld_sector_emission_eligible(
    turn: TurnInfo,
    *,
    pin: Planet | None,
    player_count: int | None = None,
) -> bool:
    """True when Core should emit homeworld sector ``regionOverlays``."""
    if pin is None:
        return False
    return homeworld_sector_geometry_eligible(turn, player_count=player_count)


def resolve_viewpoint_pin_planet(
    view: HomeworldCandidateView,
    planets: Sequence[Planet],
    *,
    shell_perspective: int | None = None,
    asserted_location_planet_ids: Sequence[int] = (),
) -> Planet | None:
    """Resolve the planet that fixes homeworld sector ring rotation.

    Preference:
    1. Spectator / pseudo-observer (``shell_perspective == 0``): any asserted
       location planet on the map (lowest id), else a definite slot-anchored
       candidate.
    2. Normal shell: definite slot-anchored matching ``shell_perspective``
       (viewpoint owner's observed HW), preferring rows that are not
       location-asserted so ownership-bound asserts cannot steal the pin;
       else any definite slot-anchored (same preference).
    """
    from api.analytics.homeworld_locator.constants import SPECTATOR_PERSPECTIVE

    planet_by_id = {planet.id: planet for planet in planets}

    def _planet_if_present(planet_id: int) -> Planet | None:
        return planet_by_id.get(planet_id)

    if shell_perspective == SPECTATOR_PERSPECTIVE:
        for planet_id in sorted(set(asserted_location_planet_ids)):
            planet = _planet_if_present(planet_id)
            if planet is not None:
                return planet
        for row in view.candidates:
            if row.location_asserted:
                planet = _planet_if_present(row.planet_id)
                if planet is not None:
                    return planet

    def _first_definite_slot_anchored(
        *,
        required_perspective: int | None,
        prefer_not_location_asserted: bool,
    ) -> Planet | None:
        matches = []
        for row in view.candidates:
            if row.confidence_tier != CONFIDENCE_DEFINITE:
                continue
            if row.perspective is None:
                continue
            if required_perspective is not None and row.perspective != required_perspective:
                continue
            if _planet_if_present(row.planet_id) is None:
                continue
            matches.append(row)
        if prefer_not_location_asserted:
            observed = [row for row in matches if not row.location_asserted]
            if observed:
                matches = observed
        if not matches:
            return None
        matches.sort(key=lambda row: row.planet_id)
        return _planet_if_present(matches[0].planet_id)

    if shell_perspective is not None and shell_perspective != SPECTATOR_PERSPECTIVE:
        # Prefer the observed viewpoint HW over location-asserted planets that
        # later acquired the same perspective via ownership bind (conqueror noise).
        pin = _first_definite_slot_anchored(
            required_perspective=shell_perspective,
            prefer_not_location_asserted=True,
        )
        if pin is not None:
            return pin

    return _first_definite_slot_anchored(
        required_perspective=None,
        prefer_not_location_asserted=True,
    )


def resolve_sector_geometry_pin(
    view: HomeworldCandidateView,
    planets: Sequence[Planet],
    *,
    shell_perspective: int | None = None,
) -> Planet | None:
    """Resolve the planet that pins sector ring geometry for layout and overlays.

    Prefer ``view.sector_pin_planet_id`` when that planet is present on the map;
    otherwise fall back to :func:`resolve_viewpoint_pin_planet`.
    """
    if view.sector_pin_planet_id is not None:
        planet_by_id = {planet.id: planet for planet in planets}
        pin = planet_by_id.get(view.sector_pin_planet_id)
        if pin is not None:
            return pin
    return resolve_viewpoint_pin_planet(
        view,
        planets,
        shell_perspective=shell_perspective,
        asserted_location_planet_ids=tuple(
            row.planet_id for row in view.candidates if row.location_asserted
        ),
    )


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


def sector_band_geometric_center(
    *,
    center: tuple[float, float],
    angle_start: float,
    angle_end: float,
    r_inner: float,
    r_outer: float,
) -> tuple[float, float]:
    """Angular mid-ray at the midpoint radius of the annular sector."""
    mid_angle = angle_start + 0.5 * annulus_angle_span(angle_start, angle_end)
    mid_radius = 0.5 * (r_inner + r_outer)
    return (
        center[0] + mid_radius * math.cos(mid_angle),
        center[1] + mid_radius * math.sin(mid_angle),
    )


def unobserved_band_sample_points(
    *,
    center: tuple[float, float],
    angle_start: float,
    angle_end: float,
    r_inner: float,
    r_outer: float,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
) -> tuple[tuple[float, float], ...]:
    """All grid samples in the annular sector that are not planet-scanned."""
    if not origins:
        return (
            sector_band_geometric_center(
                center=center,
                angle_start=angle_start,
                angle_end=angle_end,
                r_inner=r_inner,
                r_outer=r_outer,
            ),
        )

    points: list[tuple[float, float]] = []
    for x, y in iter_annulus_polar_sample_points(
        center=center,
        angle_start=angle_start,
        angle_end=angle_end,
        r_inner=r_inner,
        r_outer=r_outer,
        closed_angle=True,
    ):
        if point_covered_by_origins(x, y, origins, nebulas):
            continue
        points.append((x, y))
    return tuple(points)


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

    span, angle_samples, radial_steps = annulus_polar_sample_counts(
        angle_start=angle_start,
        angle_end=angle_end,
        r_inner=r_inner,
        r_outer=r_outer,
    )
    mid_angle = angle_start + 0.5 * span
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
    """Per-sector status, envelope, and fill for one overlay emission.

    Pin / player identity are not decided here -- those come from unique
    projected ownership on the overlay builder.
    """

    envelope_center: tuple[float, float] | None
    status: str
    fill_color: str
    candidate_count: int


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
    most_probable_planet_ids: frozenset[int] = frozenset(),
) -> _SectorOverlayDecision:
    """Envelope / status / fill for one sector. Pin is decided from projected owners."""
    candidate_count = len(sector_candidates)

    if sector_candidates:
        if is_viewpoint_sector:
            anchor = pin
        elif slot_anchored:
            anchor = _planet_closest_to_sector_mid(
                slot_anchored,
                center=center,
                angle_start=angle_start,
                angle_end=angle_end,
                r_inner=r_inner,
                r_outer=r_outer,
            )
        else:
            most_probable = [
                planet for planet in sector_candidates if planet.id in most_probable_planet_ids
            ]
            if most_probable:
                anchor = (
                    most_probable[0]
                    if len(most_probable) == 1
                    else _planet_closest_to_sector_mid(
                        most_probable,
                        center=center,
                        angle_start=angle_start,
                        angle_end=angle_end,
                        r_inner=r_inner,
                        r_outer=r_outer,
                    )
                )
            else:
                anchor = _planet_closest_to_sector_mid(
                    sector_candidates,
                    center=center,
                    angle_start=angle_start,
                    angle_end=angle_end,
                    r_inner=r_inner,
                    r_outer=r_outer,
                )
        status = STATUS_INCOMPLETE if is_incomplete else STATUS_OK
        return _SectorOverlayDecision(
            envelope_center=(float(anchor.x), float(anchor.y)),
            status=status,
            fill_color=SECTOR_COLOR,
            candidate_count=candidate_count,
        )

    if is_incomplete:
        # Fog placeholder: geometric band center (not closest-to-C sample).
        return _SectorOverlayDecision(
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
        envelope_center=None,
        status=STATUS_ERROR,
        fill_color=ERROR_SECTOR_COLOR,
        candidate_count=0,
    )


def _provenance_kind_counts(
    provenances: Sequence[OwnershipProvenance],
) -> tuple[tuple[str, int], ...]:
    """Per-kind multiplicity for ownership evidence (sorted by kind)."""
    counts: dict[str, int] = {}
    for row in provenances:
        counts[row.kind] = counts.get(row.kind, 0) + 1
    return tuple(sorted(counts.items()))


def _possible_owners_for_sector(
    members: Sequence[SectorOwnerMember],
    *,
    label_by_slot: Mapping[int, str] | None = None,
) -> tuple[MapRegionPossibleOwner, ...] | None:
    if not members:
        return None
    labels = dict(label_by_slot or ())
    return tuple(
        MapRegionPossibleOwner(
            owner_slot=member.owner_slot,
            provenance_kinds=tuple(sorted({row.kind for row in member.provenances})),
            player_label=labels.get(member.owner_slot),
            provenance_kind_counts=_provenance_kind_counts(member.provenances),
        )
        for member in sorted(members, key=lambda row: row.owner_slot)
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
    race_id_by_owner_slot: Mapping[int, int],
    nebulas: Sequence[NebulaCenter] = (),
    most_probable_planet_ids: frozenset[int] = frozenset(),
    sector_owner_sets: Mapping[int, tuple[SectorOwnerMember, ...]] | None = None,
    possible_owner_label_by_slot: Mapping[int, str] | None = None,
    location_definite_planet_ids: frozenset[int] = frozenset(),
    perspective_by_planet_id: Mapping[int, int] | None = None,
) -> tuple[MapRegionOverlay, ...]:
    """Build one boundary overlay per equal angular sector.

    ``is_pinned`` means the projected possible-owner set has exactly one
    member (max-strength contenders, then drop slots uniquely settled on
    another sector). Slot-anchored candidates are not a pin test; they only
    prefer envelope placement when present.

    ``possible_owner_label_by_slot`` maps ownership-evidence owner slots to
    roster identity strings (``username (race)``) for ``possibleOwners`` and
    for pinned-sector ``playerLabel``.

    ``most_probable_planet_ids`` are layout-prior selections; envelopes with
    no slot-anchored planet center on those when present so disks align with
    most-probable markers.

    ``location_definite_planet_ids`` upgrades preferred-candidate ownership
    strength for overlay projection (ADR 0010). Sector ``possibleOwners`` are
    projected (winning-strength + cross-sector settled trim) -- not raw durable
    membership. ``perspective_by_planet_id`` supplies slot-anchored owner slots
    so definite location pins also settle owners for cross-sector trim.
    ``race_id_by_owner_slot`` is required for ownership strength projection
    (empty map allowed when no race context).
    """
    if player_count < 2:
        return ()
    if r_outer < r_inner:
        raise ValueError("r_outer must be >= r_inner")

    owner_labels = dict(possible_owner_label_by_slot or ())
    perspectives = dict(perspective_by_planet_id or ())
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

    owner_sets = project_sector_owner_sets_with_location_pins(
        dict(sector_owner_sets or ()),
        candidate_planet_ids_by_sector=[
            [planet.id for planet in sector_planets] for sector_planets in candidates_by_sector
        ],
        location_definite_planet_ids=location_definite_planet_ids,
        perspective_by_planet_id=perspectives,
        race_id_by_owner_slot=race_id_by_owner_slot,
    )

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
            most_probable_planet_ids=most_probable_planet_ids,
        )

        disks: tuple[MapRegionOverlayDisk, ...] = ()
        if decision.envelope_center is not None:
            ex, ey = decision.envelope_center
            disks = envelope_disks_at(ex, ey)

        vertices, edges = annular_sector_boundary(
            center=center,
            angle_start=angle_start,
            angle_end=angle_end,
            r_inner=r_inner,
            r_outer=r_outer,
        )
        projection = owner_sets.get(
            index,
            SectorOwnerOverlayProjection(members=(), winning_strength=None),
        )
        owner_slot = unique_projected_owner_slot(projection)
        overlays.append(
            boundary_to_overlay(
                kind=KIND_HOMEWORLD_SECTOR,
                overlay_id=f"homeworld-sector-{index}",
                fill_color=decision.fill_color,
                fill_opacity=0.0,
                vertices=vertices,
                edges=edges,
                disks=disks,
                is_pinned=owner_slot is not None,
                status=decision.status,
                candidate_count=decision.candidate_count,
                player_label=(owner_labels.get(owner_slot) if owner_slot is not None else None),
                possible_owners=_possible_owners_for_sector(
                    projection.members,
                    label_by_slot=owner_labels,
                ),
                ownership_winning_strength=projection.winning_strength,
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
    sector_owner_sets: Mapping[int, tuple[SectorOwnerMember, ...]] | None = None,
) -> tuple[MapRegionOverlay, ...]:
    """Emit sector overlays for a shell turn when the emission gate passes."""
    if get_config().homeworld_locator.use_player_homeworld_sidebar:
        return ()
    pin = resolve_sector_geometry_pin(
        view,
        turn.planets,
        shell_perspective=shell_perspective,
    )
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
    most_probable_ids = frozenset(row.planet_id for row in view.candidates if row.is_most_probable)
    location_definite_ids = frozenset(
        row.planet_id for row in view.candidates if row.confidence_tier == CONFIDENCE_DEFINITE
    )
    perspective_by_planet = {
        row.planet_id: row.perspective for row in view.candidates if row.perspective is not None
    }
    resolved_game_id = game_id if game_id is not None else turn.settings.id
    owner_slot_labels = possible_owner_labels_for_sets(
        turn,
        sector_owner_sets,
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
        most_probable_planet_ids=most_probable_ids,
        sector_owner_sets=sector_owner_sets,
        possible_owner_label_by_slot=owner_slot_labels,
        location_definite_planet_ids=location_definite_ids,
        perspective_by_planet_id=perspective_by_planet,
        race_id_by_owner_slot=race_id_by_owner_slot(turn),
    )


def format_pinned_player_label(player: Player, races_by_id: Mapping[int, Race]) -> str:
    """Roster identity ``username (race name)`` for sector owner labels."""
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


def possible_owner_labels_for_sets(
    turn: TurnInfo,
    sector_owner_sets: Mapping[int, tuple[SectorOwnerMember, ...]] | None,
    *,
    shell_perspective: int | None = None,
    game_info: GameInfo | None = None,
    game_id: int | None = None,
) -> dict[int, str]:
    """Map ownership-evidence owner slots to roster identity labels."""
    if not sector_owner_sets:
        return {}
    races_by_id = {race.id: race for race in turn.races}
    labels: dict[int, str] = {}
    for members in sector_owner_sets.values():
        for member in members:
            if member.owner_slot in labels:
                continue
            player = player_for_homeworld_perspective(
                turn,
                member.owner_slot,
                shell_perspective=shell_perspective,
                game_info=game_info,
                game_id=game_id,
            )
            if player is None:
                continue
            labels[member.owner_slot] = format_pinned_player_label(player, races_by_id)
    return labels
