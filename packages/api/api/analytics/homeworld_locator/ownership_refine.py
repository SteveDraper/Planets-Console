"""Accumulate homeworld ownership evidence on the durable aggregate (#269)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from api.analytics.fleet.scoreboard_ship_totals import iter_current_turn_scores
from api.analytics.homeworld_locator.layout_distributions_asset import LayoutDistributionsAsset
from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE, SectorOwnerMember
from api.analytics.homeworld_locator.ownership_evidence import (
    apply_nearby_planet_ownership,
    apply_preferred_candidate_ownership,
    apply_unique_sector_envelope_pin,
    intersect_owner_possible_sectors,
    preferred_candidate_in_sector,
    preferred_sector_hw_position,
    reachable_sector_indexes,
    resolve_ship_built_turn,
    travel_envelope_radius_ly,
)
from api.analytics.homeworld_locator.ownership_projection import (
    project_sector_owner_sets_with_location_pins,
    unique_projected_owner_slot,
)
from api.analytics.homeworld_locator.sector_partition import build_homeworld_sector_partition
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldEvidenceAggregate,
)
from api.analytics.turn_roster import race_id_by_owner_slot
from api.concepts.ship_limit import total_reported_ships
from api.models.game import TurnInfo


def sector_owner_sets_to_dict(
    sector_owner_sets: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...],
) -> dict[int, tuple[SectorOwnerMember, ...]]:
    return dict(sector_owner_sets)


def sector_owner_sets_from_dict(
    sector_owner_sets: Mapping[int, tuple[SectorOwnerMember, ...]],
) -> tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...]:
    return tuple(sorted(sector_owner_sets.items(), key=lambda row: row[0]))


def owner_possible_sectors_to_dict(
    owner_possible_sectors: tuple[tuple[int, tuple[int, ...]], ...],
) -> dict[int, frozenset[int]]:
    return {owner_slot: frozenset(indexes) for owner_slot, indexes in owner_possible_sectors}


def owner_possible_sectors_from_dict(
    owner_possible_sectors: Mapping[int, frozenset[int]],
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    return tuple(
        (owner_slot, tuple(sorted(indexes)))
        for owner_slot, indexes in sorted(owner_possible_sectors.items(), key=lambda row: row[0])
    )


def _scoreboard_totals_by_turn(
    *,
    shell_turn: int,
    ensure_floor: int,
    load_turn: Callable[[int], TurnInfo | None],
) -> dict[int, int]:
    totals: dict[int, int] = {}
    for turn_number in range(ensure_floor, shell_turn + 1):
        turn = load_turn(turn_number)
        if turn is None:
            continue
        scores = list(iter_current_turn_scores(turn))
        if not scores:
            continue
        totals[turn_number] = total_reported_ships(scores)
    return totals


OwnershipSectorTuple = tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...]
OwnerPossibleSectorsTuple = tuple[tuple[int, tuple[int, ...]], ...]


def accumulate_ownership_evidence_for_turn(
    prior: HomeworldEvidenceAggregate,
    *,
    turn: TurnInfo,
    candidates: Sequence[HomeworldCandidateRecord],
    fleet_built_turns: Mapping[int, int],
    load_turn: Callable[[int], TurnInfo | None],
    ensure_floor: int | None = None,
    layout_asset: LayoutDistributionsAsset | None = None,
) -> tuple[OwnershipSectorTuple, OwnerPossibleSectorsTuple]:
    """Advance durable ownership fields by one shell turn."""
    sector_owner_sets = sector_owner_sets_to_dict(prior.sector_owner_sets)
    owner_possible = owner_possible_sectors_to_dict(prior.owner_possible_sectors)

    context = build_homeworld_sector_partition(
        turn,
        candidates=candidates,
        baseline_turn=prior.baseline_turn,
        layout_asset=layout_asset,
        asserted_location_planet_ids=tuple(
            row.planet_id for row in candidates if row.location_asserted
        ),
    )
    if context is None:
        return prior.sector_owner_sets, prior.owner_possible_sectors

    shell_turn = turn.settings.turn
    from api.concepts.accelerated_scoreboard import accelerated_ensure_floor

    floor = (
        ensure_floor
        if ensure_floor is not None
        else accelerated_ensure_floor(turn.settings, shell_turn)
    )
    scoreboard_totals = _scoreboard_totals_by_turn(
        shell_turn=shell_turn,
        ensure_floor=floor,
        load_turn=load_turn,
    )
    planets_by_id = {planet.id: planet for planet in turn.planets}
    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    engines_by_id = {engine.id: engine for engine in turn.engines}
    most_probable_ids = frozenset(prior.most_probable_planet_ids)
    sector_positions = {
        index: preferred_sector_hw_position(
            context.candidates_by_sector[index],
            planets_by_id=planets_by_id,
            most_probable_planet_ids=most_probable_ids,
            sector_mid_xy=context.sector_mids[index],
        )
        for index in range(context.player_count)
    }

    for ship in turn.ships:
        owner_slot = ship.ownerid
        if owner_slot < 1:
            continue
        built_turn, age_source = resolve_ship_built_turn(
            ship.id,
            fleet_built_turns=fleet_built_turns,
            scoreboard_totals_by_turn=scoreboard_totals,
        )
        if built_turn is None or age_source is None:
            continue
        radius_ly = travel_envelope_radius_ly(
            ship,
            shell_turn=shell_turn,
            built_turn=built_turn,
            hulls_by_id=hulls_by_id,
            engines_by_id=engines_by_id,
        )
        if radius_ly is None:
            continue
        reachable = reachable_sector_indexes(
            ship_x=ship.x,
            ship_y=ship.y,
            radius_ly=radius_ly,
            sector_positions=sector_positions,
        )
        if not reachable:
            continue
        current = owner_possible.get(owner_slot)
        narrowed = intersect_owner_possible_sectors(current, reachable)
        owner_possible[owner_slot] = narrowed
        sector_owner_sets = apply_unique_sector_envelope_pin(
            sector_owner_sets,
            owner_slot=owner_slot,
            possible_sectors=narrowed,
            turn=shell_turn,
            ship_id=ship.id,
            radius_ly=radius_ly,
            age_source=age_source,
        )

    for index in range(context.player_count):
        sector_candidates = context.candidates_by_sector[index]
        sector_mid = context.sector_mids[index]
        preferred = preferred_candidate_in_sector(
            sector_candidates,
            most_probable_planet_ids=most_probable_ids,
            mid_xy=sector_mid,
            planets_by_id=planets_by_id,
        )
        sector_owner_sets = apply_preferred_candidate_ownership(
            sector_owner_sets,
            sector_index=index,
            preferred=preferred,
            planets_by_id=planets_by_id,
            turn=shell_turn,
        )
        sector_owner_sets = apply_nearby_planet_ownership(
            sector_owner_sets,
            sector_index=index,
            candidate_planets=context.candidate_planets_by_sector[index],
            all_planets=turn.planets,
            turn=shell_turn,
        )

    return (
        sector_owner_sets_from_dict(sector_owner_sets),
        owner_possible_sectors_from_dict(owner_possible),
    )


def _bind_unbound_to_unique_owners(
    candidates: Sequence[HomeworldCandidateRecord],
    *,
    unique_owner_by_sector: Mapping[int, int],
    planet_sector_index: Mapping[int, int],
) -> tuple[HomeworldCandidateRecord, ...]:
    if not unique_owner_by_sector:
        return tuple(candidates)
    bound: list[HomeworldCandidateRecord] = []
    for row in candidates:
        if row.perspective is not None:
            bound.append(row)
            continue
        sector_index = planet_sector_index.get(row.planet_id)
        if sector_index is None:
            bound.append(row)
            continue
        owner_slot = unique_owner_by_sector.get(sector_index)
        if owner_slot is None:
            bound.append(row)
            continue
        bound.append(replace(row, perspective=owner_slot))
    return tuple(bound)


def apply_unique_owner_orphan_bind(
    candidates: Sequence[HomeworldCandidateRecord],
    aggregate: HomeworldEvidenceAggregate,
    *,
    turn: TurnInfo,
    layout_asset: LayoutDistributionsAsset | None = None,
    shell_perspective: int | None = None,
    asserted_location_planet_ids: Sequence[int] = (),
) -> tuple[HomeworldCandidateRecord, ...]:
    """Bind unbound candidates when a sector has a unique projected owner.

    Uniqueness is the overlay projection: max-strength contenders, then drop
    slots already uniquely settled on another sector. Same test as overlay
    ``is_pinned``. Iterates to fixpoint so a bind-created definite pin can
    settle the next sector in the same pass. Existing ``perspective`` values
    are preserved.
    """
    sector_owner_sets = sector_owner_sets_to_dict(aggregate.sector_owner_sets)
    if not sector_owner_sets:
        return tuple(candidates)

    context = build_homeworld_sector_partition(
        turn,
        candidates=candidates,
        baseline_turn=aggregate.baseline_turn,
        layout_asset=layout_asset,
        shell_perspective=shell_perspective,
        asserted_location_planet_ids=asserted_location_planet_ids,
    )
    if context is None:
        return tuple(candidates)

    planet_ids_by_sector = [
        [planet.id for planet in sector_planets]
        for sector_planets in context.candidate_planets_by_sector
    ]
    location_definite_planet_ids = frozenset(
        row.planet_id for row in candidates if row.confidence_tier == CONFIDENCE_DEFINITE
    )
    race_ids = race_id_by_owner_slot(turn)
    current = tuple(candidates)
    for _ in range(context.player_count):
        projected = project_sector_owner_sets_with_location_pins(
            sector_owner_sets,
            candidate_planet_ids_by_sector=planet_ids_by_sector,
            location_definite_planet_ids=location_definite_planet_ids,
            perspective_by_planet_id={
                row.planet_id: row.perspective for row in current if row.perspective is not None
            },
            race_id_by_owner_slot=race_ids,
        )
        unique_owner_by_sector: dict[int, int] = {}
        for sector_index, projection in projected.items():
            owner_slot = unique_projected_owner_slot(projection)
            if owner_slot is not None:
                unique_owner_by_sector[sector_index] = owner_slot
        next_bound = _bind_unbound_to_unique_owners(
            current,
            unique_owner_by_sector=unique_owner_by_sector,
            planet_sector_index=context.planet_sector_index,
        )
        if next_bound == current:
            return next_bound
        current = next_bound
    return current
