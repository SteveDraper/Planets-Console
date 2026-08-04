"""Homeworld location evidence: origin-distance matching and single-SB promotion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    PROVENANCE_BASELINE_PROFILE,
    PROVENANCE_ORIGIN_DISTANCE,
    HomeworldSingleStarbasePromotion,
    LocationProvenance,
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


def definite_candidate_planet_ids(
    candidates: Sequence[HomeworldCandidateRecord],
) -> tuple[int, ...]:
    """Planet ids whose durable candidate row is currently definite (baseline pins)."""
    return tuple(row.planet_id for row in candidates if row.confidence_tier == CONFIDENCE_DEFINITE)


def baseline_profile_location_provenances(
    *,
    baseline_turn: int,
    definite_planet_ids: Sequence[int],
) -> tuple[LocationProvenance, ...]:
    """Mint strong baseline-profile location provenances for definite baseline pins."""
    return tuple(
        LocationProvenance(
            kind=PROVENANCE_BASELINE_PROFILE,
            turn=baseline_turn,
            planet_id=planet_id,
        )
        for planet_id in sorted(set(definite_planet_ids))
    )


def collect_machine_location_provenances(
    *,
    prior_location_provenances: Sequence[LocationProvenance] = (),
    origin_distance_observations: Sequence[OriginDistanceObservation] = (),
    single_starbase_promotions: Sequence[HomeworldSingleStarbasePromotion] = (),
    baseline_turn: int | None = None,
    baseline_definite_planet_ids: Sequence[int] = (),
) -> tuple[LocationProvenance, ...]:
    """Rebuild machine location provenances from durable evidence facts.

    Baseline-profile rows are carried from *prior* (minted at floor write) and
    backfilled from *baseline_definite_planet_ids* when missing so legacy
    aggregates without profiles cannot lose baseline pins to weak OD-only lists.
    Origin-distance and single-starbase rows are derived from the observation /
    promotion collections so refine stays the single write path for those kinds.
    """
    rows: list[LocationProvenance] = [
        row for row in prior_location_provenances if row.kind == PROVENANCE_BASELINE_PROFILE
    ]
    seen: set[tuple[str, int, int]] = {(row.kind, row.turn, row.planet_id) for row in rows}

    def _add(kind: str, turn: int, planet_id: int) -> None:
        key = (kind, turn, planet_id)
        if key in seen:
            return
        seen.add(key)
        rows.append(LocationProvenance(kind=kind, turn=turn, planet_id=planet_id))

    if baseline_turn is not None and baseline_definite_planet_ids:
        for seed in baseline_profile_location_provenances(
            baseline_turn=baseline_turn,
            definite_planet_ids=baseline_definite_planet_ids,
        ):
            _add(seed.kind, seed.turn, seed.planet_id)

    for observation in origin_distance_observations:
        for planet_id in observation.matched_planet_ids:
            _add(PROVENANCE_ORIGIN_DISTANCE, observation.turn, planet_id)

    for promotion in single_starbase_promotions:
        _add(promotion.kind, promotion.turn, promotion.planet_id)

    return tuple(rows)
