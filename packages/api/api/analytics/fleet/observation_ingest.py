"""Ingest direct ship sightings from TurnInfo.ships into fleet ledgers."""

from __future__ import annotations

import uuid
from dataclasses import replace

from api.analytics.fleet.id_bound_ingest import tighten_inferred_ship_id_bounds
from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetAlibi,
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetEvidenceEventKind,
    FleetFieldBounded,
    FleetFieldConstraint,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetLastSeen,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
)
from api.models.game import TurnInfo
from api.models.ship import Ship

TURN_SHIPS_SOURCE = "turnInfo.ships"

_DIRECT_OBSERVATION_EVENT_KINDS = frozenset({"sighting", "position_update"})


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
        ingest_player_ship_observations(
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
    """Apply turn-T ship sightings and id-bound tightening for one player ledger."""
    turn = turn_context.turn
    turn_number = turn.settings.turn
    full_information = ledger.player_id == perspective

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
        )

    if turn_context.max_ship_id_bound is not None:
        tighten_inferred_ship_id_bounds(ledger, turn, shell_turn=turn_number)


def record_has_direct_observation(record: FleetShipRecord) -> bool:
    """True when the record carries a turnInfo.ships sighting or position update."""
    return any(event.kind in _DIRECT_OBSERVATION_EVENT_KINDS for event in record.events)


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
) -> None:
    record = _find_active_record_for_ship(ledger, ship.id)
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

    if record is None:
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
    observed_hull_id = observed_option_set.hull_id
    if observed_hull_id is not None:
        matching = [
            existing
            for existing in record.build_option_sets
            if existing.hull_id == observed_hull_id
        ]
        if not matching:
            record.build_option_sets = [observed_option_set]
            record.display_default_option_set_index = 0
            return
        record.build_option_sets = [
            _merge_option_set_observation_locks(existing, observed_option_set)
            for existing in matching
        ]
        record.display_default_option_set_index = 0
        return
    record.build_option_sets = [
        _merge_option_set_observation_locks(existing, observed_option_set)
        for existing in record.build_option_sets
    ]


def _merge_option_set_observation_locks(
    existing: FleetBuildOptionSet,
    observed: FleetBuildOptionSet,
) -> FleetBuildOptionSet:
    """Merge positively observed component ids onto one already-compatible set.

    Callers must only pass ``existing`` sets whose ``hull_id`` already matches
    ``observed.hull_id`` when the observation locked a hull.
    """
    return replace(
        existing,
        hull_id=observed.hull_id if observed.hull_id is not None else existing.hull_id,
        engine_id=observed.engine_id if observed.engine_id is not None else existing.engine_id,
        beam_id=observed.beam_id if observed.beam_id is not None else existing.beam_id,
        torp_id=observed.torp_id if observed.torp_id is not None else existing.torp_id,
        beam_count=(
            observed.beam_count if observed.beam_count is not None else existing.beam_count
        ),
        launcher_count=(
            observed.launcher_count
            if observed.launcher_count is not None
            else existing.launcher_count
        ),
    )


def _find_active_record_for_ship(
    ledger: FleetAcquisitionLedger,
    ship_id: int,
) -> FleetShipRecord | None:
    for record in ledger.records:
        if record.disposition != "active":
            continue
        if ship_id_matches_constraint(record.fields.ship_id, ship_id):
            return record
    return None


def ship_id_matches_constraint(constraint: FleetFieldConstraint, ship_id: int) -> bool:
    if isinstance(constraint, FleetFieldKnown):
        return constraint.value == ship_id
    if isinstance(constraint, FleetFieldBounded):
        bound = constraint.value
        if not isinstance(bound, (int, float)):
            return False
        if constraint.operator == "lte":
            return ship_id <= bound
        if constraint.operator == "lt":
            return ship_id < bound
        if constraint.operator == "gte":
            return ship_id >= bound
        if constraint.operator == "gt":
            return ship_id > bound
        if constraint.operator == "eq":
            return ship_id == bound
    return False


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
