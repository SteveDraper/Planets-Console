"""Compose baseline profile, cluster constraint, and circular ring geometry."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence, Set

from api.analytics.homeworld_locator.baseline_profile import unique_baseline_profile_match
from api.analytics.homeworld_locator.cluster import (
    count_cluster_neighbors,
)
from api.analytics.homeworld_locator.cluster_fow_credit import (
    cluster_band_fow_credit,
    estimate_traditional_planet_density,
    meets_homeworld_cluster_constraint_with_credit,
)
from api.analytics.homeworld_locator.constants import ATTRIBUTION_USER_ASSERTED
from api.analytics.homeworld_locator.cull_candidates import TCullable
from api.analytics.homeworld_locator.geometry import (
    find_circular_ring_homeworld_sites,
    resolve_map_center,
    sector_index_for_angle,
)
from api.analytics.homeworld_locator.layout_distributions_asset import (
    LayoutDistributionsAsset,
    load_default_layout_distributions_asset,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    InferredHomeworldCandidate,
)
from api.concepts.game_category import GameCategory
from api.concepts.homeworld_layout import supports_circular_round_candidate_geometry
from api.concepts.map_region_coverage import CoverageOrigin
from api.concepts.stellar_cartography.nebula_visibility import NebulaCenter, distance_ly
from api.concepts.warp_well import planet_is_planetoid
from api.models.game import GameSettings
from api.models.planet import Planet


def layout_center_distance_band(
    settings: GameSettings,
    *,
    player_count: int,
    layout_asset: LayoutDistributionsAsset | None = None,
) -> tuple[float, float] | None:
    """Return asset center-distance support band when sector paint applies; else None.

    Same epic|standard + circular + round gate as homeworld sector overlays.
    """
    if not supports_circular_round_candidate_geometry(settings):
        return None
    category = GameCategory.from_game_settings(settings, player_count=player_count)
    if category not in (GameCategory.EPIC, GameCategory.STANDARD):
        return None
    asset = layout_asset if layout_asset is not None else load_default_layout_distributions_asset()
    return asset.center_distance_band(category)


def planet_in_center_distance_band(
    planet: Planet,
    *,
    center: tuple[float, float],
    r_inner: float,
    r_outer: float,
) -> bool:
    """True when planet lies in the closed annular band around ``center``."""
    dist = distance_ly(planet.x, planet.y, center[0], center[1])
    return r_inner <= dist <= r_outer


def cull_co_sector_candidates_after_definites(
    candidates: Sequence[TCullable],
    planets_by_id: Mapping[int, Planet],
    *,
    center: tuple[float, float],
    player_count: int,
    pin_angle: float,
) -> tuple[TCullable, ...]:
    """Enforce one inferred homeworld per Circular sector after definites exist.

    Once a sector has a definite, other inferred possibles in that wedge are not
    competing HW sites. Evidence promotion can create additional inferred definites
    in the same sector; those are also dropped so neighborhood cull does not treat
    them as true HWs. User-asserted rows are never culled. Applies only when
    ``player_count >= 2``.

    Inferred definite precedence within a sector: slot-anchored (``perspective`` set)
    over orphans; ties by lower planet id. Any user-asserted definite in the sector
    suppresses all inferred definites there.
    """
    if player_count < 2 or not candidates:
        return tuple(candidates)

    center_x, center_y = center

    def _sector_for(row: TCullable) -> int | None:
        planet = planets_by_id.get(row.planet_id)
        if planet is None:
            return None
        angle = math.atan2(planet.y - center_y, planet.x - center_x)
        return sector_index_for_angle(angle, pin_angle=pin_angle, player_count=player_count)

    definites_by_sector: dict[int, list[TCullable]] = {}
    for row in candidates:
        if row.confidence_tier != CONFIDENCE_DEFINITE:
            continue
        sector = _sector_for(row)
        if sector is None:
            continue
        definites_by_sector.setdefault(sector, []).append(row)
    if not definites_by_sector:
        return tuple(candidates)

    kept_definite_ids: set[int] = set()
    for sector_rows in definites_by_sector.values():
        user_asserted = [row for row in sector_rows if row.attribution == ATTRIBUTION_USER_ASSERTED]
        if user_asserted:
            kept_definite_ids.update(row.planet_id for row in user_asserted)
            continue
        inferred = [row for row in sector_rows if row.attribution != ATTRIBUTION_USER_ASSERTED]
        if not inferred:
            continue
        winner = min(
            inferred,
            key=lambda row: (
                0 if row.perspective is not None else 1,
                row.planet_id,
            ),
        )
        kept_definite_ids.add(winner.planet_id)

    definite_sectors = set(definites_by_sector)
    kept: list[TCullable] = []
    for row in candidates:
        if row.attribution == ATTRIBUTION_USER_ASSERTED:
            kept.append(row)
            continue
        if row.confidence_tier == CONFIDENCE_DEFINITE:
            if row.planet_id in kept_definite_ids:
                kept.append(row)
            continue
        sector = _sector_for(row)
        if sector is not None and sector in definite_sectors:
            continue
        kept.append(row)
    return tuple(kept)


def infer_homeworld_baseline_candidates(
    planets: Sequence[Planet],
    *,
    settings: GameSettings,
    viewpoint_player_id: int,
    viewpoint_perspective: int,
    viewpoint_race_id: int,
    player_count: int,
    starbase_planet_ids: Set[int],
    min_baseline_clans: int,
    scan_origins: Sequence[CoverageOrigin],
    map_center: tuple[float, float] | None = None,
    layout_asset: LayoutDistributionsAsset | None = None,
    nebulas: Sequence[NebulaCenter] = (),
    cluster_fow_density_credit_multiplier: float = 1.0,
) -> tuple[InferredHomeworldCandidate, ...]:
    """Infer slot-anchored and orphan homeworld candidates from a baseline turn.

    Viewpoint unique baseline-profile match -> definite slot-anchored. On circular +
    round maps, remaining ring sites become orphan possibles only when they also
    meet the **homeworld cluster constraint** (geometry AND cluster -- not OR).
    Cluster-constraint matches also yield orphan possibles when ring math does not
    apply (or for off-ring planets). When the layout-asset epic|standard band
    applies (same gate as sector overlays), orphan candidates outside that
    center-distance support are never emitted. After emission, possibles that share
    a sector with a definite are culled (one HW per Circular sector). Rival slots
    are not cross-product bound in v1 baseline. Debris-disk planetoids are never
    candidates and never count toward cluster neighborhood minima.

    Cluster candidature applies FoW density credit for unobserved very-close /
    close annulus area using ``scan_origins`` / ``nebulas`` and
    ``cluster_fow_density_credit_multiplier``. ``scan_origins`` is required:
    pass the perspective planet-scan origins from ensure. An empty sequence is
    valid and means full-band unobserved credit (no scan coverage model).

    ``viewpoint_player_id`` matches planet ``ownerid`` (Player.id).
    ``viewpoint_perspective`` is the 1-based shell storage slot written on
    slot-anchored candidates -- it is not interchangeable with player id.
    """
    pin = unique_baseline_profile_match(
        planets,
        owner_id=viewpoint_player_id,
        race_id=viewpoint_race_id,
        settings=settings,
        starbase_planet_ids=starbase_planet_ids,
        min_baseline_clans=min_baseline_clans,
    )

    emitted: dict[int, InferredHomeworldCandidate] = {}
    center = map_center if map_center is not None else resolve_map_center(planets)
    density = estimate_traditional_planet_density(
        planets,
        settings,
        origins=scan_origins,
        nebulas=nebulas,
        map_center=center,
    )

    def _meets_cluster(planet: Planet) -> bool:
        known = count_cluster_neighbors(planet, planets)
        credit = cluster_band_fow_credit(
            planet,
            density_per_ly2=density,
            origins=scan_origins,
            nebulas=nebulas,
            credit_multiplier=cluster_fow_density_credit_multiplier,
        )
        return meets_homeworld_cluster_constraint_with_credit(known, credit, settings)

    use_ring = (
        pin is not None
        and supports_circular_round_candidate_geometry(settings)
        and player_count >= 2
    )
    band = (
        layout_center_distance_band(
            settings,
            player_count=player_count,
            layout_asset=layout_asset,
        )
        if use_ring
        else None
    )

    def _orphan_allowed(planet: Planet) -> bool:
        if band is None:
            return True
        return planet_in_center_distance_band(
            planet,
            center=center,
            r_inner=band[0],
            r_outer=band[1],
        )

    if pin is not None:
        emitted[pin.id] = InferredHomeworldCandidate(
            planet_id=pin.id,
            perspective=viewpoint_perspective,
            confidence_tier=CONFIDENCE_DEFINITE,
        )

        if use_ring:
            for site in find_circular_ring_homeworld_sites(
                planets,
                center=center,
                player_count=player_count,
                pin=pin,
            ):
                if site.id == pin.id:
                    continue
                if not _orphan_allowed(site):
                    continue
                if not _meets_cluster(site):
                    continue
                emitted.setdefault(
                    site.id,
                    InferredHomeworldCandidate(
                        planet_id=site.id,
                        perspective=None,
                        confidence_tier=CONFIDENCE_POSSIBLE,
                    ),
                )

    for planet in planets:
        if planet.id in emitted:
            continue
        if planet_is_planetoid(planet):
            continue
        if not _orphan_allowed(planet):
            continue
        if not _meets_cluster(planet):
            continue
        emitted[planet.id] = InferredHomeworldCandidate(
            planet_id=planet.id,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        )

    rows = tuple(sorted(emitted.values(), key=lambda row: row.planet_id))
    if not use_ring or pin is None:
        return rows

    pin_angle = math.atan2(pin.y - center[1], pin.x - center[0])
    return cull_co_sector_candidates_after_definites(
        rows,
        {planet.id: planet for planet in planets},
        center=center,
        player_count=player_count,
        pin_angle=pin_angle,
    )


def apply_co_sector_candidate_cull(
    candidates: Sequence[TCullable],
    planets: Sequence[Planet],
    *,
    settings: GameSettings,
    player_count: int,
    map_center: tuple[float, float] | None = None,
) -> tuple[TCullable, ...]:
    """Cull co-sector possibles when Circular geometry and a definite pin exist.

    No-op when ring/sector math does not apply or no definite planet is on the map.
    Pin angle is taken from a slot-anchored definite when present, else any definite.
    """
    if (
        player_count < 2
        or not candidates
        or not supports_circular_round_candidate_geometry(settings)
    ):
        return tuple(candidates)

    planets_by_id = {planet.id: planet for planet in planets}
    definites = [row for row in candidates if row.confidence_tier == CONFIDENCE_DEFINITE]
    if not definites:
        return tuple(candidates)

    # Prefer slot-anchored definite (has perspective) to fix ring rotation.
    definites = sorted(
        definites,
        key=lambda row: (row.perspective is None, row.planet_id),
    )
    pin_planet: Planet | None = None
    for row in definites:
        pin_planet = planets_by_id.get(row.planet_id)
        if pin_planet is not None:
            break
    if pin_planet is None:
        return tuple(candidates)

    center = map_center if map_center is not None else resolve_map_center(planets)
    pin_angle = math.atan2(pin_planet.y - center[1], pin_planet.x - center[0])
    return cull_co_sector_candidates_after_definites(
        candidates,
        planets_by_id,
        center=center,
        player_count=player_count,
        pin_angle=pin_angle,
    )
