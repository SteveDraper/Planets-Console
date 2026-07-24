"""Fleet count collapse: absorb surplus unobserved rows onto id-known survivors."""

from __future__ import annotations

import uuid

from api.analytics.fleet.field_constraints import (
    known_built_turn_value,
    record_has_direct_observation,
    ship_id_matches_constraint,
)
from api.analytics.fleet.scoreboard_ship_totals import iter_current_turn_scores
from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetEvidenceEvent,
    FleetFieldBounded,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipClass,
    FleetShipRecord,
)
from api.concepts.hulls import hull_is_freighter
from api.models.components import Hull
from api.models.game import TurnInfo
from api.models.player import Score

COUNT_COLLAPSE_SOURCE = "fleet.count_collapse"

AbsorbableShipId = FleetFieldUnknown | FleetFieldBounded


def apply_fleet_count_collapse(
    ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
) -> None:
    """Collapse surplus unobserved unknowns onto knowns per ship class. Mutates ledger."""
    turn_number = turn.settings.turn
    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    score = _player_score(turn, ledger.player_id)
    if score is None:
        return

    for ship_class in ("warship", "freighter"):
        implied = _implied_count(score, ship_class)
        class_records = _active_records_for_class(ledger, ship_class, hulls_by_id)
        active_class = len(class_records)
        surplus = active_class - implied
        if surplus <= 0:
            continue

        absorbables: list[tuple[int, FleetShipRecord, AbsorbableShipId]] = []
        for index, record in enumerate(ledger.records):
            if record not in class_records:
                continue
            absorbable_ship_id = _absorbable_ship_id(record)
            if absorbable_ship_id is None:
                continue
            absorbables.append((index, record, absorbable_ship_id))
        survivors = [record for record in class_records if _is_survivor(record, hulls_by_id)]
        absorbables.sort(key=lambda item: _absorbable_sort_key(item[2], item[1], item[0]))

        free_survivors = list(survivors)
        absorbable_index = 0
        while surplus > 0 and absorbable_index < len(absorbables):
            _, absorbable, absorbable_ship_id = absorbables[absorbable_index]
            absorbable_index += 1
            compatible: list[tuple[int, FleetShipRecord]] = [
                (known_id, survivor)
                for survivor in free_survivors
                if (known_id := _known_ship_id(survivor)) is not None
                and _ship_id_admits_survivor(absorbable_ship_id, known_id)
            ]
            if not compatible:
                continue
            known_id, survivor = min(compatible, key=lambda item: item[0])
            candidate_set_size = len(compatible)
            surplus -= 1
            _collapse_one(
                absorbable,
                survivor,
                turn=turn_number,
                ship_class=ship_class,
                known_ship_id=known_id,
                candidate_set_size=candidate_set_size,
                remaining_surplus=surplus,
                absorbable_ship_id=absorbable_ship_id,
            )
            free_survivors.remove(survivor)


def _player_score(turn: TurnInfo, player_id: int) -> Score | None:
    for score in iter_current_turn_scores(turn):
        if score.ownerid == player_id:
            return score
    return None


def _implied_count(score: Score, ship_class: FleetShipClass) -> int:
    if ship_class == "warship":
        return score.capitalships
    return score.freighters


def _active_records_for_class(
    ledger: FleetAcquisitionLedger,
    ship_class: FleetShipClass,
    hulls_by_id: dict[int, Hull],
) -> list[FleetShipRecord]:
    # Active rows with no attributable ship class are excluded from per-class pools.
    records: list[FleetShipRecord] = []
    for record in ledger.records:
        if record.disposition != "active":
            continue
        record_class = _record_ship_class(record, hulls_by_id)
        if record_class == ship_class:
            records.append(record)
    return records


def _record_ship_class(
    record: FleetShipRecord,
    hulls_by_id: dict[int, Hull],
) -> FleetShipClass | None:
    survivor_class = _record_ship_class_survivor(record, hulls_by_id)
    if survivor_class is not None:
        return survivor_class
    return _record_ship_class_absorbable(record)


def _record_ship_class_absorbable(record: FleetShipRecord) -> FleetShipClass | None:
    for event in record.events:
        if event.kind != "scoreboard_delta":
            continue
        ship_class = event.payload.get("shipClass")
        if ship_class in ("warship", "freighter"):
            return ship_class  # type: ignore[return-value]
    return None


def _record_ship_class_survivor(
    record: FleetShipRecord,
    hulls_by_id: dict[int, Hull],
) -> FleetShipClass | None:
    hull_constraint = record.fields.hull
    if not isinstance(hull_constraint, FleetFieldKnown):
        return None
    if not isinstance(hull_constraint.value, int):
        return None
    hull = hulls_by_id.get(hull_constraint.value)
    if hull is None:
        return None
    return "freighter" if hull_is_freighter(hull) else "warship"


def _absorbable_ship_id(record: FleetShipRecord) -> AbsorbableShipId | None:
    if record.disposition != "active":
        return None
    if record_has_direct_observation(record):
        return None
    ship_id = record.fields.ship_id
    if not isinstance(ship_id, (FleetFieldUnknown, FleetFieldBounded)):
        return None
    if _record_ship_class_absorbable(record) is None:
        return None
    return ship_id


def _is_survivor(record: FleetShipRecord, hulls_by_id: dict[int, Hull]) -> bool:
    if record.disposition != "active":
        return False
    if _known_ship_id(record) is None:
        return False
    return _record_ship_class_survivor(record, hulls_by_id) is not None


def _known_ship_id(record: FleetShipRecord) -> int | None:
    ship_id = record.fields.ship_id
    if isinstance(ship_id, FleetFieldKnown) and isinstance(ship_id.value, int):
        return ship_id.value
    return None


def _ship_id_admits_survivor(constraint: AbsorbableShipId, ship_id: int) -> bool:
    """Collapse-local admit: Unknown matches any survivor id; else shared constraint match.

    Keep Unknown universal-admit here only. Shared ``ship_id_matches_constraint`` is
    used by observation matching and must not treat Unknown as a match for every id.
    """
    if isinstance(constraint, FleetFieldUnknown):
        return True
    return ship_id_matches_constraint(constraint, ship_id)


def _absorbable_sort_key(
    ship_id: AbsorbableShipId,
    record: FleetShipRecord,
    ledger_index: int,
) -> tuple[object, ...]:
    built_turn = known_built_turn_value(record)
    built_turn_key = built_turn if built_turn is not None else float("inf")
    return (
        _constraint_tightness_key(ship_id),
        built_turn_key,
        ledger_index,
    )


def _constraint_tightness_key(constraint: AbsorbableShipId) -> tuple[int, int | float]:
    """Sort key for absorbable shipId: eq, then numeric bounds, then fully unknown."""
    if isinstance(constraint, FleetFieldBounded):
        bound = constraint.value
        if not isinstance(bound, (int, float)):
            return (5, 0)
        if constraint.operator == "eq":
            return (0, 0)
        if constraint.operator in ("lte", "lt"):
            return (2, bound)
        if constraint.operator in ("gte", "gt"):
            return (3, -bound)
        return (5, 0)
    return (4, 0)


def _constraint_tightness_label(constraint: AbsorbableShipId) -> str:
    if isinstance(constraint, FleetFieldBounded):
        return f"{constraint.operator}:{constraint.value}"
    return "unknown"


def _collapse_one(
    absorbable: FleetShipRecord,
    survivor: FleetShipRecord,
    *,
    turn: int,
    ship_class: FleetShipClass,
    known_ship_id: int,
    candidate_set_size: int,
    remaining_surplus: int,
    absorbable_ship_id: AbsorbableShipId,
) -> None:
    constraint_tightness = _constraint_tightness_label(absorbable_ship_id)

    if isinstance(survivor.fields.built_turn, FleetFieldUnknown) and isinstance(
        absorbable.fields.built_turn, FleetFieldKnown
    ):
        survivor.fields.built_turn = absorbable.fields.built_turn
    if not survivor.build_option_sets and absorbable.build_option_sets:
        survivor.build_option_sets = list(absorbable.build_option_sets)
        survivor.display_default_option_set_index = absorbable.display_default_option_set_index

    absorbable.fields.ship_id = FleetFieldKnown(known_ship_id)
    absorbable.disposition = "merged"

    payload: dict[str, object] = {
        "peerRecordId": survivor.record_id,
        "shipId": known_ship_id,
        "shipClass": ship_class,
        "constraintTightness": constraint_tightness,
        "tieBreak": "ship_id",
        "candidateSetSize": candidate_set_size,
        "remainingSurplus": remaining_surplus,
    }
    append_fleet_evidence_event(
        absorbable,
        _new_count_collapse_event(turn=turn, payload=payload),
    )
    survivor_payload = {
        **payload,
        "peerRecordId": absorbable.record_id,
    }
    append_fleet_evidence_event(
        survivor,
        _new_count_collapse_event(turn=turn, payload=survivor_payload),
    )


def _new_count_collapse_event(
    *,
    turn: int,
    payload: dict[str, object],
) -> FleetEvidenceEvent:
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind="count_collapse",
        turn=turn,
        source=COUNT_COLLAPSE_SOURCE,
        payload=payload,
    )
