"""Compose baseline profile, cluster constraint, and circular ring geometry."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence, Set
from typing import Protocol, TypeVar

from api.analytics.homeworld_locator.baseline_profile import unique_baseline_profile_match
from api.analytics.homeworld_locator.cluster import (
    count_cluster_neighbors,
    meets_homeworld_cluster_constraint,
)
from api.analytics.homeworld_locator.constants import ATTRIBUTION_USER_ASSERTED
from api.analytics.homeworld_locator.geometry import (
    find_circular_ring_homeworld_sites,
    resolve_map_center,
    sector_index_for_angle,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    InferredHomeworldCandidate,
)
from api.concepts.homeworld_layout import supports_circular_round_candidate_geometry
from api.concepts.warp_well import planet_is_planetoid
from api.models.game import GameSettings
from api.models.planet import Planet


class _CullableCandidate(Protocol):
    @property
    def planet_id(self) -> int: ...

    @property
    def confidence_tier(self) -> str: ...


TCullable = TypeVar("TCullable", bound=_CullableCandidate)


def _candidate_attribution(row: object) -> str | None:
    return getattr(row, "attribution", None)


def cull_co_sector_candidates_after_definites(
    candidates: Sequence[TCullable],
    planets_by_id: Mapping[int, Planet],
    *,
    center: tuple[float, float],
    player_count: int,
    pin_angle: float,
) -> tuple[TCullable, ...]:
    """Drop non-definite candidates that share a sector with a definite homeworld.

    Circular layout has one HW per sector. Once a sector has a definite, other
    possibles in that wedge are not competing HW sites. User-asserted rows are
    never culled. Applies only when ``player_count >= 2``.
    """
    if player_count < 2 or not candidates:
        return tuple(candidates)

    center_x, center_y = center
    definite_sectors: set[int] = set()
    for row in candidates:
        if row.confidence_tier != CONFIDENCE_DEFINITE:
            continue
        planet = planets_by_id.get(row.planet_id)
        if planet is None:
            continue
        angle = math.atan2(planet.y - center_y, planet.x - center_x)
        definite_sectors.add(
            sector_index_for_angle(angle, pin_angle=pin_angle, player_count=player_count)
        )
    if not definite_sectors:
        return tuple(candidates)

    kept: list[TCullable] = []
    for row in candidates:
        if _candidate_attribution(row) == ATTRIBUTION_USER_ASSERTED:
            kept.append(row)
            continue
        if row.confidence_tier == CONFIDENCE_DEFINITE:
            kept.append(row)
            continue
        planet = planets_by_id.get(row.planet_id)
        if planet is None:
            kept.append(row)
            continue
        angle = math.atan2(planet.y - center_y, planet.x - center_x)
        sector = sector_index_for_angle(angle, pin_angle=pin_angle, player_count=player_count)
        if sector in definite_sectors:
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
    map_center: tuple[float, float] | None = None,
) -> tuple[InferredHomeworldCandidate, ...]:
    """Infer slot-anchored and orphan homeworld candidates from a baseline turn.

    Viewpoint unique baseline-profile match -> definite slot-anchored. On circular +
    round maps, remaining ring sites become orphan possibles. Cluster-constraint
    matches also yield orphan possibles (including when ring math does not apply).
    After emission, possibles that share a sector with a definite are culled (one HW
    per Circular sector). Rival slots are not cross-product bound in v1 baseline.
    Debris-disk planetoids are never candidates and never count toward cluster
    neighborhood minima.

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
    use_ring = (
        pin is not None
        and supports_circular_round_candidate_geometry(settings)
        and player_count >= 2
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
        counts = count_cluster_neighbors(planet, planets)
        if not meets_homeworld_cluster_constraint(counts, settings):
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
        key=lambda row: (getattr(row, "perspective", None) is None, row.planet_id),
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
