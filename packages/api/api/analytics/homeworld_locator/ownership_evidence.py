"""Homeworld ownership evidence: travel envelopes and planetary ownership sightings.

Pure domain helpers for #269. Orchestrator / fleet DAG wiring is Phase 2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from api.analytics.homeworld_locator.models import (
    AGE_SOURCE_FLEET_BUILT_TURN,
    AGE_SOURCE_SHIP_ID_SCOREBOARD,
    CONFIDENCE_DEFINITE,
    PROVENANCE_NEARBY_PLANET_OWNERSHIP,
    PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
    PROVENANCE_SHIP_TRAVEL_ENVELOPE,
    OwnershipProvenance,
    SectorOwnerMember,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord
from api.concepts.hull_abilities import hull_has_gravitonic_movement, hull_has_hyperjump
from api.concepts.planet_connections.wells import max_travel_distance
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.concepts.warp_well import planet_is_planetoid
from api.models.components import Engine, Hull
from api.models.planet import Planet
from api.models.ship import Ship

DEFAULT_ENGINE_WARP_WHEN_UNKNOWN = 9
NEARBY_OWNERSHIP_RADIUS_LY = max_travel_distance(9, gravitonic_movement=True)
"""162 LY -- gravitonic warp-9 travel; nearby planetary ownership cap."""


def earliest_built_turn_from_ship_id(
    ship_id: int,
    totals_by_turn: Mapping[int, int],
) -> int | None:
    """Earliest turn where scoreboard total ships is >= ``ship_id`` (max-age bound)."""
    if ship_id < 1 or not totals_by_turn:
        return None
    eligible = [turn for turn, total in totals_by_turn.items() if total >= ship_id]
    if not eligible:
        return None
    return min(eligible)


def resolve_ship_built_turn(
    ship_id: int,
    *,
    fleet_built_turns: Mapping[int, int],
    scoreboard_totals_by_turn: Mapping[int, int],
) -> tuple[int | None, str | None]:
    """Return ``(built_turn, age_source)`` preferring fleet, else id/scoreboard max age."""
    fleet_turn = fleet_built_turns.get(ship_id)
    if fleet_turn is not None:
        return fleet_turn, AGE_SOURCE_FLEET_BUILT_TURN
    earliest = earliest_built_turn_from_ship_id(ship_id, scoreboard_totals_by_turn)
    if earliest is None:
        return None, None
    return earliest, AGE_SOURCE_SHIP_ID_SCOREBOARD


def travel_turns_at_shell(*, shell_turn: int, built_turn: int) -> int:
    return max(0, shell_turn - built_turn)


def engine_warp_capability(
    ship: Ship,
    *,
    engines_by_id: Mapping[int, Engine],
) -> int:
    """Max warp from catalog engines; unknown / missing → warp 9."""
    engine = engines_by_id.get(ship.engineid)
    if engine is None:
        return DEFAULT_ENGINE_WARP_WHEN_UNKNOWN
    tech = int(engine.techlevel)
    if tech < 1:
        return DEFAULT_ENGINE_WARP_WHEN_UNKNOWN
    return min(tech, DEFAULT_ENGINE_WARP_WHEN_UNKNOWN)


def travel_envelope_radius_ly(
    ship: Ship,
    *,
    shell_turn: int,
    built_turn: int,
    hulls_by_id: Mapping[int, Hull],
    engines_by_id: Mapping[int, Engine],
) -> float | None:
    """Max travel LY from age × warp². ``None`` when the ship is HYP-capable (ignored)."""
    hull = hulls_by_id.get(ship.hullid)
    if hull is not None and hull_has_hyperjump(hull):
        return None
    gravitonic = hull is not None and hull_has_gravitonic_movement(hull)
    warp = engine_warp_capability(ship, engines_by_id=engines_by_id)
    turns = travel_turns_at_shell(shell_turn=shell_turn, built_turn=built_turn)
    per_turn = max_travel_distance(warp, gravitonic)
    return float(turns) * per_turn


def preferred_candidate_in_sector(
    candidates: Sequence[HomeworldCandidateRecord],
    *,
    most_probable_planet_ids: frozenset[int] = frozenset(),
    mid_xy: tuple[float, float] | None = None,
    planets_by_id: Mapping[int, Planet] | None = None,
) -> HomeworldCandidateRecord | None:
    """Definite > most-probable > closest-to-mid among the given sector candidates."""
    if not candidates:
        return None
    definites = [row for row in candidates if row.confidence_tier == CONFIDENCE_DEFINITE]
    if len(definites) == 1:
        return definites[0]
    if len(definites) > 1:
        return min(definites, key=lambda row: row.planet_id)
    most_probable = [row for row in candidates if row.planet_id in most_probable_planet_ids]
    if len(most_probable) == 1:
        return most_probable[0]
    if len(most_probable) > 1:
        return min(most_probable, key=lambda row: row.planet_id)
    if mid_xy is not None and planets_by_id is not None:
        mx, my = mid_xy

        def _dist(row: HomeworldCandidateRecord) -> tuple[float, int]:
            planet = planets_by_id.get(row.planet_id)
            if planet is None:
                return (float("inf"), row.planet_id)
            return (distance_ly(planet.x, planet.y, mx, my), row.planet_id)

        return min(candidates, key=_dist)
    return min(candidates, key=lambda row: row.planet_id)


def preferred_sector_hw_position(
    candidates: Sequence[HomeworldCandidateRecord],
    *,
    planets_by_id: Mapping[int, Planet],
    most_probable_planet_ids: frozenset[int] = frozenset(),
    sector_mid_xy: tuple[float, float],
) -> tuple[float, float]:
    """Preferred HW map position for envelope reachability (candidate or sector mid)."""
    preferred = preferred_candidate_in_sector(
        candidates,
        most_probable_planet_ids=most_probable_planet_ids,
        mid_xy=sector_mid_xy,
        planets_by_id=planets_by_id,
    )
    if preferred is not None:
        planet = planets_by_id.get(preferred.planet_id)
        if planet is not None:
            return (float(planet.x), float(planet.y))
    return sector_mid_xy


def reachable_sector_indexes(
    *,
    ship_x: int,
    ship_y: int,
    radius_ly: float,
    sector_positions: Mapping[int, tuple[float, float]],
) -> frozenset[int]:
    """Sectors whose preferred HW position lies within ``radius_ly`` of the ship."""
    if radius_ly < 0:
        return frozenset()
    reachable: set[int] = set()
    for sector_index, (px, py) in sector_positions.items():
        if distance_ly(ship_x, ship_y, px, py) <= radius_ly + 1e-9:
            reachable.add(sector_index)
    return frozenset(reachable)


def intersect_owner_possible_sectors(
    current: frozenset[int] | None,
    reachable: frozenset[int],
) -> frozenset[int]:
    """Intersect reachable sectors into the owner's remaining possible set.

    ``None`` means uninitialized (all sectors still possible) -- first observation
    replaces with ``reachable``.
    """
    if current is None:
        return frozenset(reachable)
    return frozenset(current & reachable)


def add_provenance_to_sector_owner_set(
    owner_set: Sequence[SectorOwnerMember],
    *,
    owner_slot: int,
    provenance: OwnershipProvenance,
) -> tuple[SectorOwnerMember, ...]:
    """Add or merge provenance for ``owner_slot``; preserves other members."""
    if owner_slot < 1:
        return tuple(owner_set)
    by_slot = {member.owner_slot: member for member in owner_set}
    existing = by_slot.get(owner_slot)
    if existing is None:
        by_slot[owner_slot] = SectorOwnerMember(
            owner_slot=owner_slot,
            provenances=(provenance,),
        )
    else:
        if provenance in existing.provenances:
            return tuple(sorted(by_slot.values(), key=lambda row: row.owner_slot))
        by_slot[owner_slot] = SectorOwnerMember(
            owner_slot=owner_slot,
            provenances=(*existing.provenances, provenance),
        )
    return tuple(sorted(by_slot.values(), key=lambda row: row.owner_slot))


def apply_unique_sector_envelope_pin(
    sector_owner_sets: Mapping[int, tuple[SectorOwnerMember, ...]],
    *,
    owner_slot: int,
    possible_sectors: frozenset[int],
    turn: int,
    ship_id: int,
    radius_ly: float,
    age_source: str,
) -> dict[int, tuple[SectorOwnerMember, ...]]:
    """When exactly one sector remains for ``owner_slot``, add envelope provenance there."""
    updated = dict(sector_owner_sets)
    if owner_slot < 1 or len(possible_sectors) != 1:
        return updated
    sector_index = next(iter(possible_sectors))
    provenance = OwnershipProvenance(
        kind=PROVENANCE_SHIP_TRAVEL_ENVELOPE,
        turn=turn,
        ship_id=ship_id,
        radius_ly=radius_ly,
        age_source=age_source,
    )
    prior = updated.get(sector_index, ())
    updated[sector_index] = add_provenance_to_sector_owner_set(
        prior,
        owner_slot=owner_slot,
        provenance=provenance,
    )
    return updated


def apply_preferred_candidate_ownership(
    sector_owner_sets: Mapping[int, tuple[SectorOwnerMember, ...]],
    *,
    sector_index: int,
    preferred: HomeworldCandidateRecord | None,
    planets_by_id: Mapping[int, Planet],
    turn: int,
) -> dict[int, tuple[SectorOwnerMember, ...]]:
    """Known ownerid on the preferred HW candidate adds that slot to the sector set."""
    updated = dict(sector_owner_sets)
    if preferred is None:
        return updated
    planet = planets_by_id.get(preferred.planet_id)
    if planet is None or planet_is_planetoid(planet) or planet.ownerid < 1:
        return updated
    provenance = OwnershipProvenance(
        kind=PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
        turn=turn,
        planet_id=planet.id,
    )
    prior = updated.get(sector_index, ())
    updated[sector_index] = add_provenance_to_sector_owner_set(
        prior,
        owner_slot=planet.ownerid,
        provenance=provenance,
    )
    return updated


def apply_nearby_planet_ownership(
    sector_owner_sets: Mapping[int, tuple[SectorOwnerMember, ...]],
    *,
    sector_index: int,
    candidate_planets: Sequence[Planet],
    all_planets: Sequence[Planet],
    turn: int,
    nearby_radius_ly: float = NEARBY_OWNERSHIP_RADIUS_LY,
) -> dict[int, tuple[SectorOwnerMember, ...]]:
    """Known ownerids within ``nearby_radius_ly`` of any sector candidate HW add to the set."""
    updated = dict(sector_owner_sets)
    traditional_candidates = [
        planet for planet in candidate_planets if not planet_is_planetoid(planet)
    ]
    if not traditional_candidates:
        return updated
    candidate_ids = {planet.id for planet in traditional_candidates}
    prior = updated.get(sector_index, ())
    for planet in all_planets:
        if planet_is_planetoid(planet) or planet.ownerid < 1:
            continue
        if planet.id in candidate_ids:
            continue
        for candidate in traditional_candidates:
            dist = distance_ly(planet.x, planet.y, candidate.x, candidate.y)
            if dist <= nearby_radius_ly + 1e-9:
                provenance = OwnershipProvenance(
                    kind=PROVENANCE_NEARBY_PLANET_OWNERSHIP,
                    turn=turn,
                    planet_id=planet.id,
                    distance_ly=dist,
                )
                prior = add_provenance_to_sector_owner_set(
                    prior,
                    owner_slot=planet.ownerid,
                    provenance=provenance,
                )
                break
    updated[sector_index] = prior
    return updated
