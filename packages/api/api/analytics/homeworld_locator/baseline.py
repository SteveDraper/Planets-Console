"""Compose baseline profile, cluster constraint, and circular ring geometry."""

from __future__ import annotations

from collections.abc import Sequence, Set

from api.analytics.homeworld_locator.baseline_profile import unique_baseline_profile_match
from api.analytics.homeworld_locator.cluster import (
    count_cluster_neighbors,
    meets_homeworld_cluster_constraint,
)
from api.analytics.homeworld_locator.geometry import (
    find_circular_ring_homeworld_sites,
    resolve_map_center,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    InferredHomeworldCandidate,
)
from api.concepts.homeworld_layout import supports_circular_round_candidate_geometry
from api.models.game import GameSettings
from api.models.planet import Planet


def infer_homeworld_baseline_candidates(
    planets: Sequence[Planet],
    *,
    settings: GameSettings,
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
    Rival slots are not cross-product bound in v1 baseline.
    """
    pin = unique_baseline_profile_match(
        planets,
        owner_id=viewpoint_perspective,
        race_id=viewpoint_race_id,
        settings=settings,
        starbase_planet_ids=starbase_planet_ids,
        min_baseline_clans=min_baseline_clans,
    )

    emitted: dict[int, InferredHomeworldCandidate] = {}

    if pin is not None:
        emitted[pin.id] = InferredHomeworldCandidate(
            planet_id=pin.id,
            perspective=viewpoint_perspective,
            confidence_tier=CONFIDENCE_DEFINITE,
        )

        if supports_circular_round_candidate_geometry(settings) and player_count >= 2:
            center = map_center if map_center is not None else resolve_map_center(planets)
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
        counts = count_cluster_neighbors(planet, planets)
        if not meets_homeworld_cluster_constraint(counts, settings):
            continue
        emitted[planet.id] = InferredHomeworldCandidate(
            planet_id=planet.id,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        )

    return tuple(sorted(emitted.values(), key=lambda row: row.planet_id))
