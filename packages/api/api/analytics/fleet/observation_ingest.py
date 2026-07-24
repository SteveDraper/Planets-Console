"""Ingest direct ship sightings from TurnInfo.ships into fleet ledgers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Literal

from api.analytics.fleet.count_collapse import apply_fleet_count_collapse
from api.analytics.fleet.field_constraints import (
    known_built_turn_value,
    record_has_direct_observation,
    ship_id_matches_constraint,
)
from api.analytics.fleet.id_bound_ingest import tighten_inferred_ship_id_bounds_if_computable
from api.analytics.fleet.observation_option_locks import (
    LockFilterEmptyPolicy,
    ObservationComponentLocks,
    observation_locks_from_option_set,
    option_set_compatible_with_locks,
    resolve_option_sets_respecting_locks,
)
from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetAlibi,
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetEvidenceEventKind,
    FleetFieldConstraint,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetLastSeen,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
)
from api.concepts.hulls import hull_is_freighter, is_generic_freighter_sentinel_hull_id
from api.concepts.races import is_solar_federation
from api.models.components import Hull
from api.models.game import TurnInfo
from api.models.ship import Ship

TURN_SHIPS_SOURCE = "turnInfo.ships"

OptionSetMatchTieBreak = Literal["rank_weight", "built_turn", "ledger_order"]

# Higher rank value = higher preference when selecting among candidates (max wins).
OptionSetMatchKind = Literal["standard", "generic_freighter", "fed_refit"]
_MATCH_KIND_RANK: dict[OptionSetMatchKind, int] = {
    "standard": 2,
    "generic_freighter": 1,
    "fed_refit": 0,
}


@dataclass(frozen=True, slots=True)
class _OptionSetMatchSelection:
    """Winning id-bound arbitration pick for one sighting."""

    record: FleetShipRecord
    option_set_index: int
    solution_rank_weight: int
    tie_break: OptionSetMatchTieBreak
    match_kind: OptionSetMatchKind
    candidate_set_size: int


def apply_id_bounds_then_observations(
    ledger: FleetAcquisitionLedger,
    turn_context: FleetTurnContext,
    *,
    perspective: int,
) -> None:
    """Canonical ordering: id bounds, then sightings, then count collapse.

    Use this whenever observation ingest follows acquisition or refine on a shell
    turn. Call ``ingest_player_ship_observations`` alone only when bounds were
    already applied for the same shell turn and no new unbound inferred rows
    were created since.
    """
    tighten_inferred_ship_id_bounds_if_computable(ledger, turn_context)
    ingest_player_ship_observations(ledger, turn_context, perspective=perspective)
    apply_fleet_count_collapse(ledger, turn_context.turn)


def ingest_turn_ship_observations(
    snapshot: FleetTurnSnapshot,
    turn: TurnInfo,
    *,
    turn_context: FleetTurnContext | None = None,
) -> FleetTurnSnapshot:
    """Apply turn-T ship sightings to every player ledger in the snapshot."""
    resolved_context = (
        turn_context if turn_context is not None else FleetTurnContext.from_turn(turn)
    )
    for ledger in snapshot.players:
        apply_id_bounds_then_observations(
            ledger,
            resolved_context,
            perspective=snapshot.perspective,
        )
    return snapshot


def ingest_player_ship_observations(
    ledger: FleetAcquisitionLedger,
    turn_context: FleetTurnContext,
    *,
    perspective: int,
) -> None:
    """Apply turn-T ship sightings for one player ledger (matching only).

    Prefer ``apply_id_bounds_then_observations`` so id bounds run first when a
    max ship-id bound is computable. Callers that invoke this directly must
    already have tightened bounds for this shell turn (and refined inferred
    option sets when scores evidence is available) so arbitration sees
    lock-compatible candidates.
    """
    turn = turn_context.turn
    turn_number = turn.settings.turn
    full_information = ledger.player_id == perspective
    race_id = _race_id_for_player(turn, ledger.player_id)
    hulls_by_id = {hull.id: hull for hull in turn.hulls}

    for ship in turn.ships:
        if ship.turnkilled != 0:
            continue
        if ship.ownerid != ledger.player_id:
            continue
        _ingest_ship_sighting(
            ledger,
            ship,
            turn,
            turn_number=turn_number,
            full_information=full_information,
            race_id=race_id,
            hulls_by_id=hulls_by_id,
        )


def observation_established_full_fit(record: FleetShipRecord) -> bool:
    """True when a direct observation locked a complete component fit.

    Full-information sightings (``ledger.player_id == perspective``) always lock
    hull, engine, beams, and launchers -- including known-zero weapon axes.
    Partial foreign sightings leave unreliable axes unknown, so they do not
    satisfy this predicate unless every component was positively observed.
    """
    if not record_has_direct_observation(record):
        return False
    fields = record.fields
    return (
        isinstance(fields.hull, FleetFieldKnown)
        and isinstance(fields.engine, FleetFieldKnown)
        and isinstance(fields.beams, FleetFieldKnown)
        and isinstance(fields.launchers, FleetFieldKnown)
    )


def _ingest_ship_sighting(
    ledger: FleetAcquisitionLedger,
    ship: Ship,
    turn: TurnInfo,
    *,
    turn_number: int,
    full_information: bool,
    race_id: int | None,
    hulls_by_id: dict[int, Hull],
) -> None:
    last_seen = FleetLastSeen(
        turn=turn_number,
        x=ship.x,
        y=ship.y,
        planet_id=_planet_id_at_coordinates(turn, ship.x, ship.y),
    )
    observed_fields = _observed_fields_from_ship(ship, full_information=full_information)
    observed_option_set = _observed_build_option_set_from_ship(
        ship,
        full_information=full_information,
    )
    observation_locks = observation_locks_from_option_set(observed_option_set)

    exact = _find_active_record_with_known_ship_id(ledger, ship.id)
    if exact is not None:
        _update_matched_record(
            exact,
            ship,
            observed_fields=observed_fields,
            observed_option_set=observed_option_set,
            last_seen=last_seen,
            turn_number=turn_number,
            full_information=full_information,
            option_set_match=None,
        )
        return

    selection = _select_option_set_match(
        ledger,
        ship_id=ship.id,
        observation_locks=observation_locks,
        observed_hull_id=ship.hullid if ship.hullid > 0 else None,
        race_id=race_id,
        hulls_by_id=hulls_by_id,
    )
    if selection is None:
        record = FleetShipRecord(
            record_id=str(uuid.uuid4()),
            fields=observed_fields,
            build_option_sets=[observed_option_set],
            display_default_option_set_index=0,
            last_seen=last_seen,
        )
        append_fleet_evidence_event(
            record,
            _new_evidence_event(
                kind="sighting",
                turn=turn_number,
                payload=_ship_sighting_payload(ship),
            ),
        )
        ledger.records.append(record)
        return

    _update_matched_record(
        selection.record,
        ship,
        observed_fields=observed_fields,
        observed_option_set=observed_option_set,
        last_seen=last_seen,
        turn_number=turn_number,
        full_information=full_information,
        option_set_match=selection,
    )


def _update_matched_record(
    record: FleetShipRecord,
    ship: Ship,
    *,
    observed_fields: FleetShipRecordFields,
    observed_option_set: FleetBuildOptionSet,
    last_seen: FleetLastSeen,
    turn_number: int,
    full_information: bool,
    option_set_match: _OptionSetMatchSelection | None,
) -> None:
    if option_set_match is not None:
        append_fleet_evidence_event(
            record,
            _new_evidence_event(
                kind="option_set_match",
                turn=turn_number,
                payload={
                    "shipId": ship.id,
                    "optionSetIndex": option_set_match.option_set_index,
                    "solutionRankWeight": option_set_match.solution_rank_weight,
                    "tieBreak": option_set_match.tie_break,
                    "matchKind": option_set_match.match_kind,
                    "candidateSetSize": option_set_match.candidate_set_size,
                },
            ),
        )

    prior_last_seen = record.last_seen
    position_changed = (
        prior_last_seen is None or prior_last_seen.x != ship.x or prior_last_seen.y != ship.y
    )
    record.fields = _merge_observed_fields(record.fields, observed_fields)
    _apply_observed_option_set(
        record,
        observed_option_set,
        full_information=full_information,
    )
    record.last_seen = last_seen
    append_fleet_evidence_event(
        record,
        _new_evidence_event(
            kind="position_update" if position_changed else "sighting",
            turn=turn_number,
            payload=_ship_sighting_payload(ship),
        ),
    )
    _apply_alibi_if_needed(record, sighting_turn=turn_number)


def _apply_observed_option_set(
    record: FleetShipRecord,
    observed_option_set: FleetBuildOptionSet,
    *,
    full_information: bool,
) -> None:
    """Write observation option-set ground truth without clobbering partial unknowns.

    Full-information sightings replace any prior sets with the single confirmed fit.
    Partial sightings only lock positively observed axes onto existing inferred
    alternates that already match the observed hull (or seed a hull-centric set
    when none exist / none match). Never rewrite a foreign hull id onto a
    Deep-Space-Scout-style fit -- that produced Falcon rows with 4 X-Rays.
    """
    if full_information:
        record.build_option_sets = [observed_option_set]
        record.display_default_option_set_index = 0
        return
    if not record.build_option_sets:
        record.build_option_sets = [observed_option_set]
        record.display_default_option_set_index = 0
        return
    locks = observation_locks_from_option_set(observed_option_set)
    resolved = resolve_option_sets_respecting_locks(
        record.build_option_sets,
        locks,
        on_empty=LockFilterEmptyPolicy.SEED,
        seed=observed_option_set,
    )
    record.build_option_sets = list(resolved)
    record.display_default_option_set_index = 0


def _find_active_record_with_known_ship_id(
    ledger: FleetAcquisitionLedger,
    ship_id: int,
) -> FleetShipRecord | None:
    for record in ledger.records:
        if record.disposition != "active":
            continue
        ship_id_field = record.fields.ship_id
        if isinstance(ship_id_field, FleetFieldKnown) and ship_id_field.value == ship_id:
            return record
    return None


def _select_option_set_match(
    ledger: FleetAcquisitionLedger,
    *,
    ship_id: int,
    observation_locks: ObservationComponentLocks,
    observed_hull_id: int | None,
    race_id: int | None,
    hulls_by_id: dict[int, Hull],
) -> _OptionSetMatchSelection | None:
    """Pick the best unlinked id-bound row for ``ship_id``.

    Preference: ``standard`` lock match over ``generic_freighter`` (sentinel hull 0
    onto a freighter hull) over Fed-only ``fed_refit`` (sentinel onto any hull).
    Within a kind: max rank weight, then earliest known ``builtTurn``, then ledger
    order.
    """

    @dataclass(frozen=True, slots=True)
    class _Candidate:
        record: FleetShipRecord
        option_set_index: int
        solution_rank_weight: int
        match_kind: OptionSetMatchKind
        built_turn: int | None
        ledger_index: int

    observed_hull_is_freighter = _observed_hull_is_freighter(observed_hull_id, hulls_by_id)
    fed_refit_allowed = race_id is not None and is_solar_federation(race_id)

    candidates: list[_Candidate] = []
    for ledger_index, record in enumerate(ledger.records):
        if record.disposition != "active":
            continue
        if isinstance(record.fields.ship_id, FleetFieldKnown):
            continue
        if not ship_id_matches_constraint(record.fields.ship_id, ship_id):
            continue
        if record_has_direct_observation(record):
            continue
        if not record.build_option_sets:
            continue

        matched_index: int | None = None
        matched_weight: int | None = None
        matched_kind: OptionSetMatchKind | None = None
        for index, option_set in enumerate(record.build_option_sets):
            kind = _option_set_match_kind(
                option_set,
                observation_locks,
                observed_hull_is_freighter=observed_hull_is_freighter,
                fed_refit_allowed=fed_refit_allowed,
            )
            if kind is None:
                continue
            weight = option_set.solution_rank_weight
            if matched_kind is None or _MATCH_KIND_RANK[kind] > _MATCH_KIND_RANK[matched_kind]:
                matched_kind = kind
                matched_weight = weight
                matched_index = index
                continue
            if kind != matched_kind:
                continue
            if matched_weight is None or weight > matched_weight:
                matched_weight = weight
                matched_index = index

        if matched_index is None or matched_weight is None or matched_kind is None:
            continue

        candidates.append(
            _Candidate(
                record=record,
                option_set_index=matched_index,
                solution_rank_weight=matched_weight,
                match_kind=matched_kind,
                built_turn=known_built_turn_value(record),
                ledger_index=ledger_index,
            )
        )

    if not candidates:
        return None

    winner = max(
        candidates,
        key=lambda candidate: (
            _MATCH_KIND_RANK[candidate.match_kind],
            candidate.solution_rank_weight,
            candidate.built_turn is not None,
            -(candidate.built_turn if candidate.built_turn is not None else 0),
            -candidate.ledger_index,
        ),
    )
    peers_same_kind = [
        candidate for candidate in candidates if candidate.match_kind == winner.match_kind
    ]
    tie_break: OptionSetMatchTieBreak = "rank_weight"
    peers_at_weight = [
        candidate
        for candidate in peers_same_kind
        if candidate.solution_rank_weight == winner.solution_rank_weight
    ]
    if len(peers_at_weight) > 1:
        peers_at_built_turn = [
            candidate for candidate in peers_at_weight if candidate.built_turn == winner.built_turn
        ]
        if len(peers_at_built_turn) > 1:
            tie_break = "ledger_order"
        else:
            tie_break = "built_turn"

    return _OptionSetMatchSelection(
        record=winner.record,
        option_set_index=winner.option_set_index,
        solution_rank_weight=winner.solution_rank_weight,
        tie_break=tie_break,
        match_kind=winner.match_kind,
        candidate_set_size=len(candidates),
    )


def _option_set_match_kind(
    option_set: FleetBuildOptionSet,
    observation_locks: ObservationComponentLocks,
    *,
    observed_hull_is_freighter: bool,
    fed_refit_allowed: bool,
) -> OptionSetMatchKind | None:
    if option_set_compatible_with_locks(option_set, observation_locks):
        return "standard"
    if not is_generic_freighter_sentinel_hull_id(option_set.hull_id):
        return None
    # Generic freighter sentinel: ignore hull lock; require other axes compatible.
    locks_without_hull = replace(observation_locks, hull_id=None)
    if not option_set_compatible_with_locks(option_set, locks_without_hull):
        # Fed Super Refit: unarmed military build can look like a freighter combo
        # then gain weapons later -- allow any observation as a last resort.
        if fed_refit_allowed:
            return "fed_refit"
        return None
    if observed_hull_is_freighter:
        return "generic_freighter"
    if fed_refit_allowed:
        return "fed_refit"
    return None


def _observed_hull_is_freighter(
    observed_hull_id: int | None,
    hulls_by_id: dict[int, Hull],
) -> bool:
    if observed_hull_id is None:
        return False
    hull = hulls_by_id.get(observed_hull_id)
    if hull is None:
        return False
    return hull_is_freighter(hull)


def _race_id_for_player(turn: TurnInfo, player_id: int) -> int | None:
    for player in turn.players:
        if player.id == player_id:
            return player.raceid
    if turn.player.id == player_id:
        return turn.player.raceid
    return None


def _observed_fields_from_ship(
    ship: Ship,
    *,
    full_information: bool,
) -> FleetShipRecordFields:
    built_turn = FleetFieldKnown(ship.turn) if ship.turn > 0 else FleetFieldUnknown()
    hull = FleetFieldKnown(ship.hullid) if ship.hullid > 0 else FleetFieldUnknown()
    if full_information:
        beams = (
            FleetFieldKnown(ship.beamid)
            if ship.beams > 0 and ship.beamid > 0
            else FleetFieldKnown(0)
            if ship.beams == 0
            else FleetFieldUnknown()
        )
        if ship.bays > 0 or ship.torps > 0:
            launchers = (
                FleetFieldKnown(ship.torpedoid) if ship.torpedoid > 0 else FleetFieldUnknown()
            )
        else:
            launchers = FleetFieldKnown(0)
        return FleetShipRecordFields(
            ship_id=FleetFieldKnown(ship.id),
            hull=hull,
            engine=FleetFieldKnown(ship.engineid),
            beams=beams,
            launchers=launchers,
            built_turn=built_turn,
            location=FleetFieldUnknown(),
        )

    # Partial (foreign) sighting: hull is reliable; other axes only on positive signal.
    # Fog-of-war zeros must not become Known(0) "no weapons".
    engine = FleetFieldKnown(ship.engineid) if ship.engineid > 0 else FleetFieldUnknown()
    beams = (
        FleetFieldKnown(ship.beamid) if ship.beams > 0 and ship.beamid > 0 else FleetFieldUnknown()
    )
    launchers = (
        FleetFieldKnown(ship.torpedoid)
        if ship.torpedoid > 0 and (ship.torps > 0 or ship.bays > 0)
        else FleetFieldUnknown()
    )
    return FleetShipRecordFields(
        ship_id=FleetFieldKnown(ship.id),
        hull=hull,
        engine=engine,
        beams=beams,
        launchers=launchers,
        built_turn=built_turn,
        location=FleetFieldUnknown(),
    )


def _observed_build_option_set_from_ship(
    ship: Ship,
    *,
    full_information: bool,
) -> FleetBuildOptionSet:
    """Fitted option set from a sighting.

    Full-information: single confirmed fit including known-zero weapon slot fills.
    Partial: only positively observed components -- fog zeros leave type ids and
    counts null so display can show ``?`` rather than claiming empty weapons.
    """
    hull_id = ship.hullid if ship.hullid > 0 else None
    if full_information:
        beam_count = ship.beams
        launcher_count = ship.torps
        return FleetBuildOptionSet(
            hull_id=hull_id,
            engine_id=ship.engineid if ship.engineid > 0 else None,
            beam_id=ship.beamid if beam_count > 0 and ship.beamid > 0 else None,
            torp_id=ship.torpedoid if launcher_count > 0 and ship.torpedoid > 0 else None,
            beam_count=beam_count,
            launcher_count=launcher_count,
        )
    beam_count = ship.beams if ship.beams > 0 else None
    launcher_count = ship.torps if ship.torps > 0 else None
    return FleetBuildOptionSet(
        hull_id=hull_id,
        engine_id=ship.engineid if ship.engineid > 0 else None,
        beam_id=ship.beamid if beam_count is not None and ship.beamid > 0 else None,
        torp_id=(ship.torpedoid if launcher_count is not None and ship.torpedoid > 0 else None),
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def _merge_observed_fields(
    current: FleetShipRecordFields,
    observed: FleetShipRecordFields,
) -> FleetShipRecordFields:
    return FleetShipRecordFields(
        ship_id=_merge_field_constraint(current.ship_id, observed.ship_id),
        hull=_merge_field_constraint(current.hull, observed.hull),
        engine=_merge_field_constraint(current.engine, observed.engine),
        beams=_merge_field_constraint(current.beams, observed.beams),
        launchers=_merge_field_constraint(current.launchers, observed.launchers),
        built_turn=_merge_field_constraint(current.built_turn, observed.built_turn),
        location=_merge_field_constraint(current.location, observed.location),
    )


def _merge_field_constraint(
    current: FleetFieldConstraint,
    observed: FleetFieldConstraint,
) -> FleetFieldConstraint:
    if isinstance(current, FleetFieldKnown):
        return current
    if isinstance(observed, FleetFieldKnown):
        return observed
    return current


def _apply_alibi_if_needed(record: FleetShipRecord, *, sighting_turn: int) -> None:
    if record.qualifiers.alibi is not None:
        return
    decrease_turn = _recorded_count_decrease_turn(record)
    if decrease_turn is None or sighting_turn <= decrease_turn:
        return
    record.qualifiers.alibi = FleetAlibi(
        after_turn=decrease_turn,
        sighting_turn=sighting_turn,
        source=TURN_SHIPS_SOURCE,
    )
    append_fleet_evidence_event(
        record,
        _new_evidence_event(
            kind="alibi",
            turn=sighting_turn,
            payload={
                "afterTurn": decrease_turn,
                "sightingTurn": sighting_turn,
            },
        ),
    )


def _recorded_count_decrease_turn(record: FleetShipRecord) -> int | None:
    if record.qualifiers.possibly_lost is not None:
        return record.qualifiers.possibly_lost.since_turn
    latest_decrease_turn: int | None = None
    for event in record.events:
        if event.kind != "scoreboard_delta":
            continue
        warship_delta = event.payload.get("warshipDelta", 0)
        freighter_delta = event.payload.get("freighterDelta", 0)
        if not isinstance(warship_delta, int) or isinstance(warship_delta, bool):
            continue
        if not isinstance(freighter_delta, int) or isinstance(freighter_delta, bool):
            continue
        if warship_delta + freighter_delta < 0:
            if latest_decrease_turn is None or event.turn > latest_decrease_turn:
                latest_decrease_turn = event.turn
    return latest_decrease_turn


def _planet_id_at_coordinates(turn: TurnInfo, x: int, y: int) -> int | None:
    for planet in turn.planets:
        if planet.x == x and planet.y == y:
            return planet.id
    return None


def _ship_sighting_payload(ship: Ship) -> dict[str, object]:
    return {
        "shipId": ship.id,
        "ownerId": ship.ownerid,
        "x": ship.x,
        "y": ship.y,
        "hullId": ship.hullid,
        "engineId": ship.engineid,
        "beamId": ship.beamid,
        "torpId": ship.torpedoid,
        "beamCount": ship.beams,
        "launcherCount": ship.torps,
    }


def _new_evidence_event(
    *,
    kind: FleetEvidenceEventKind,
    turn: int,
    payload: dict[str, object],
) -> FleetEvidenceEvent:
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind=kind,
        turn=turn,
        source=TURN_SHIPS_SOURCE,
        payload=payload,
    )
