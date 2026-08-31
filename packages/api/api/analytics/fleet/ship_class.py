"""Classify a fleet ship record as warship or freighter."""

from __future__ import annotations

from api.analytics.fleet.types import FleetFieldKnown, FleetShipClass, FleetShipRecord
from api.concepts.hulls import hull_is_freighter
from api.models.components import Hull


def record_ship_class(
    record: FleetShipRecord,
    hulls_by_id: dict[int, Hull],
) -> FleetShipClass | None:
    """Return warship/freighter when the record has hull or scoreboard-class evidence."""
    survivor_class = record_ship_class_from_known_hull(record, hulls_by_id)
    if survivor_class is not None:
        return survivor_class
    return record_ship_class_from_scoreboard_delta(record)


def record_ship_class_from_scoreboard_delta(record: FleetShipRecord) -> FleetShipClass | None:
    for event in record.events:
        if event.kind != "scoreboard_delta":
            continue
        ship_class = event.payload.get("shipClass")
        if ship_class in ("warship", "freighter"):
            return ship_class  # type: ignore[return-value]
    return None


def record_ship_class_from_known_hull(
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
