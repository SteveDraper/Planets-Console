"""Shared helpers for fleet field constraint and record predicates."""

from __future__ import annotations

from api.analytics.fleet.types import (
    FleetFieldBounded,
    FleetFieldConstraint,
    FleetFieldKnown,
    FleetShipRecord,
)

_DIRECT_OBSERVATION_EVENT_KINDS = frozenset({"sighting", "position_update"})


def known_positive_component_id(field: FleetFieldConstraint) -> int | None:
    if not isinstance(field, FleetFieldKnown):
        return None
    value = field.value
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def known_built_turn_value(record: FleetShipRecord) -> int | None:
    built_turn = record.fields.built_turn
    if isinstance(built_turn, FleetFieldKnown) and isinstance(built_turn.value, int):
        return built_turn.value
    return None


def record_has_direct_observation(record: FleetShipRecord) -> bool:
    """True when the record carries a turnInfo.ships sighting or position update."""
    return any(event.kind in _DIRECT_OBSERVATION_EVENT_KINDS for event in record.events)


def ship_id_matches_constraint(constraint: FleetFieldConstraint, ship_id: int) -> bool:
    """True when a concrete ship id satisfies a Known or Bounded ship_id constraint.

    ``FleetFieldUnknown`` never matches here. Callers that need Unknown as a
    universal admit (count collapse absorb pairing) must handle that locally.
    """
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
