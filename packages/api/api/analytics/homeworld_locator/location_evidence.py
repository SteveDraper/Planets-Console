"""Homeworld location evidence: origin-distance matching and single-SB promotion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    HomeworldSingleStarbasePromotion,
    OriginDistanceObservation,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord
from api.concepts.hull_abilities import hull_has_gravitonic_movement
from api.concepts.planet_connections.wells import max_travel_distance
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.models.components import Hull
from api.models.game import TurnInfo
from api.models.planet import Planet
from api.models.ship import Ship

ORIGIN_DISTANCE_MATCH_TOLERANCE_LY = 1.0
"""Inclusive LY band around each origin-distance target (design: ~±1 LY)."""

_WARP_BAND_8 = 8
_WARP_BAND_9 = 9


def origin_distance_targets(*, gravitonic_movement: bool) -> tuple[float, float]:
    """Characteristic travel distances for v1 origin-distance bands."""
    return (
        max_travel_distance(_WARP_BAND_8, gravitonic_movement),
        max_travel_distance(_WARP_BAND_9, gravitonic_movement),
    )


def matches_origin_distance_band(
    observed_distance_ly: float,
    target_distance_ly: float,
    *,
    tolerance_ly: float = ORIGIN_DISTANCE_MATCH_TOLERANCE_LY,
) -> bool:
    return abs(observed_distance_ly - target_distance_ly) <= tolerance_ly + 1e-9


def ship_matches_origin_distance_to_planet(
    ship: Ship,
    planet: Planet,
    *,
    gravitonic_movement: bool,
    tolerance_ly: float = ORIGIN_DISTANCE_MATCH_TOLERANCE_LY,
) -> bool:
    observed = distance_ly(ship.x, ship.y, planet.x, planet.y)
    return any(
        matches_origin_distance_band(observed, target, tolerance_ly=tolerance_ly)
        for target in origin_distance_targets(gravitonic_movement=gravitonic_movement)
    )


def ship_at_planet(ship: Ship, planet: Planet) -> bool:
    return ship.x == planet.x and ship.y == planet.y


def _hulls_by_id(turn: TurnInfo) -> dict[int, Hull]:
    return {hull.id: hull for hull in turn.hulls}


def ship_gravitonic_movement(ship: Ship, *, hulls_by_id: Mapping[int, Hull]) -> bool:
    hull = hulls_by_id.get(ship.hullid)
    return hull is not None and hull_has_gravitonic_movement(hull)


def candidate_planet_ids(candidates: Sequence[HomeworldCandidateRecord]) -> frozenset[int]:
    return frozenset(row.planet_id for row in candidates)


def origin_distance_candidate_planet_ids(
    ship: Ship,
    *,
    candidate_planet_ids: frozenset[int],
    planets_by_id: Mapping[int, Planet],
    gravitonic_movement: bool,
    tolerance_ly: float = ORIGIN_DISTANCE_MATCH_TOLERANCE_LY,
) -> tuple[int, ...]:
    """Match *ship* against existing homeworld candidates only (no orphan creation)."""
    matched: list[int] = []
    for planet_id in sorted(candidate_planet_ids):
        planet = planets_by_id.get(planet_id)
        if planet is None:
            continue
        if ship_matches_origin_distance_to_planet(
            ship,
            planet,
            gravitonic_movement=gravitonic_movement,
            tolerance_ly=tolerance_ly,
        ):
            matched.append(planet_id)
    return tuple(matched)


def implicated_candidate_planet_ids(
    ship: Ship,
    *,
    candidate_planet_ids: frozenset[int],
    planets_by_id: Mapping[int, Planet],
    gravitonic_movement: bool,
    tolerance_ly: float = ORIGIN_DISTANCE_MATCH_TOLERANCE_LY,
) -> tuple[int, ...]:
    """Candidates implicated by an at-planet sighting or origin-distance match."""
    implicated: list[int] = []
    for planet_id in sorted(candidate_planet_ids):
        planet = planets_by_id.get(planet_id)
        if planet is None:
            continue
        if ship_at_planet(ship, planet) or ship_matches_origin_distance_to_planet(
            ship,
            planet,
            gravitonic_movement=gravitonic_movement,
            tolerance_ly=tolerance_ly,
        ):
            implicated.append(planet_id)
    return tuple(implicated)


def upsert_origin_distance_observation(
    existing: Sequence[OriginDistanceObservation],
    *,
    turn: int,
    x: int,
    y: int,
    matched_planet_ids: Sequence[int],
) -> tuple[OriginDistanceObservation, ...]:
    """Upsert one observation keyed by (turn, x, y), unioning match set M."""
    if not matched_planet_ids:
        return tuple(existing)
    key = (turn, x, y)
    incoming = frozenset(matched_planet_ids)
    updated: list[OriginDistanceObservation] = []
    found = False
    for observation in existing:
        if (observation.turn, observation.x, observation.y) == key:
            found = True
            merged = tuple(sorted(frozenset(observation.matched_planet_ids) | incoming))
            updated.append(
                OriginDistanceObservation(
                    turn=turn,
                    x=x,
                    y=y,
                    matched_planet_ids=merged,
                )
            )
        else:
            updated.append(observation)
    if not found:
        updated.append(
            OriginDistanceObservation(
                turn=turn,
                x=x,
                y=y,
                matched_planet_ids=tuple(sorted(incoming)),
            )
        )
    return tuple(updated)


def scoreboard_starbase_count_for_owner(turn: TurnInfo, owner_id: int) -> int | None:
    if turn.settings.stealthmode:
        return None
    for score in turn.scores:
        if score.ownerid == owner_id:
            return score.starbases
    return None


def is_ship_built_on_previous_turn(
    ship: Ship,
    *,
    shell_turn: int,
    fleet_built_turn: int | None = None,
) -> bool:
    if fleet_built_turn is not None:
        return fleet_built_turn == shell_turn - 1
    return ship.turn > 0 and ship.turn == shell_turn - 1


def single_starbase_new_build_implicated_planet_id(
    ship: Ship,
    turn: TurnInfo,
    *,
    shell_turn: int,
    candidate_planet_ids: frozenset[int],
    planets_by_id: Mapping[int, Planet],
    fleet_built_turn: int | None = None,
) -> int | None:
    """Return one candidate planet for immediate promotion, or None when ineligible."""
    if not is_ship_built_on_previous_turn(
        ship, shell_turn=shell_turn, fleet_built_turn=fleet_built_turn
    ):
        return None
    starbase_count = scoreboard_starbase_count_for_owner(turn, ship.ownerid)
    if starbase_count != 1:
        return None
    hulls_by_id = _hulls_by_id(turn)
    gravitonic = ship_gravitonic_movement(ship, hulls_by_id=hulls_by_id)
    implicated = implicated_candidate_planet_ids(
        ship,
        candidate_planet_ids=candidate_planet_ids,
        planets_by_id=planets_by_id,
        gravitonic_movement=gravitonic,
    )
    if len(implicated) != 1:
        return None
    return implicated[0]


def promote_candidate_to_definite(
    candidates: Sequence[HomeworldCandidateRecord],
    *,
    planet_id: int,
) -> tuple[HomeworldCandidateRecord, ...]:
    """Promote one existing possible candidate to definite without changing homeworld owner."""
    promoted: list[HomeworldCandidateRecord] = []
    for row in candidates:
        if row.planet_id == planet_id and row.confidence_tier == CONFIDENCE_POSSIBLE:
            promoted.append(
                HomeworldCandidateRecord(
                    planet_id=row.planet_id,
                    perspective=row.perspective,
                    confidence_tier=CONFIDENCE_DEFINITE,
                    attribution=row.attribution,
                )
            )
        else:
            promoted.append(row)
    return tuple(promoted)


def record_single_starbase_promotion(
    existing_promotions: Sequence[HomeworldSingleStarbasePromotion],
    *,
    turn: int,
    planet_id: int,
) -> tuple[HomeworldSingleStarbasePromotion, ...]:
    if any(
        promotion.planet_id == planet_id and promotion.turn == turn
        for promotion in existing_promotions
    ):
        return tuple(existing_promotions)
    return (
        *existing_promotions,
        HomeworldSingleStarbasePromotion(planet_id=planet_id, turn=turn),
    )
