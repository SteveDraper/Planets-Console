"""Codecs for leftover, placeholder departures, lattice signatures, and exact-set pins.

Do not encode an unknown-loss bound as a point ``unexplainedMilitaryDelta2x``.
"""

from __future__ import annotations

from collections.abc import Sequence

from api.analytics.fleet.types import FleetShipClass
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    ExactSetDeparturePin,
    ExactSetPinRecord,
    LatticeSignature,
    PlaceholderBuild,
    PlaceholderDeparture,
    PointLeftover,
    UnknownLossBoundLeftover,
    UnknownLossLeftover,
)
from api.errors import CoreAPIError

LEFTOVER_KIND_POINT = "point"
LEFTOVER_KIND_UNKNOWN_LOSS_BOUND = "unknown_loss_bound"
PLACEHOLDER_DEPARTURE_ID = "placeholder_departure"
_VALID_SHIP_CLASSES = frozenset({"warship", "freighter"})


class UncharacterizedRosterCodecError(CoreAPIError):
    """Malformed leftover, departure, lattice-signature, or exact-set pin payload."""

    http_error = 422


def leftover_to_json(leftover: UnknownLossLeftover) -> dict[str, object]:
    """Serialize the leftover tagged union. Bound is never a point leftover."""
    if leftover.kind == LEFTOVER_KIND_POINT:
        return {
            "kind": LEFTOVER_KIND_POINT,
            "unexplainedMilitaryDelta2x": leftover.unexplained_military_delta_2x,
        }
    return {
        "kind": LEFTOVER_KIND_UNKNOWN_LOSS_BOUND,
        "lowerBound2x": leftover.lower_bound_2x,
    }


def leftover_from_json(data: object) -> UnknownLossLeftover:
    """Deserialize leftover. Rejects a bound encoded as a point leftover field."""
    payload = _require_object(data, "leftover")
    kind = payload.get("kind")
    if kind == LEFTOVER_KIND_POINT:
        return PointLeftover(
            unexplained_military_delta_2x=_require_int(
                payload.get("unexplainedMilitaryDelta2x"),
                "leftover.unexplainedMilitaryDelta2x",
            )
        )
    if kind == LEFTOVER_KIND_UNKNOWN_LOSS_BOUND:
        if "unexplainedMilitaryDelta2x" in payload:
            raise UncharacterizedRosterCodecError(
                "unknown_loss_bound leftover must not carry unexplainedMilitaryDelta2x"
            )
        return UnknownLossBoundLeftover(
            lower_bound_2x=_require_int(payload.get("lowerBound2x"), "leftover.lowerBound2x")
        )
    raise UncharacterizedRosterCodecError("leftover.kind must be point or unknown_loss_bound")


def placeholder_departure_to_json(departure: PlaceholderDeparture) -> dict[str, object]:
    """Serialize a placeholder departure. Sign lives in the type, not hull -1."""
    payload: dict[str, object] = {
        "id": PLACEHOLDER_DEPARTURE_ID,
        "shipClass": departure.ship_class,
        "count": departure.count,
    }
    if departure.counterparty_player_id is not None:
        payload["counterpartyPlayerId"] = departure.counterparty_player_id
    return payload


def placeholder_departure_from_json(data: object) -> PlaceholderDeparture:
    payload = _require_object(data, "placeholder departure")
    if payload.get("id") != PLACEHOLDER_DEPARTURE_ID:
        raise UncharacterizedRosterCodecError(
            "placeholder departure id must be placeholder_departure"
        )
    if "hullId" in payload:
        raise UncharacterizedRosterCodecError(
            "placeholder departure must not carry hullId (sign is in the type)"
        )
    count = _require_int(payload.get("count"), "placeholder departure.count")
    if count <= 0:
        raise UncharacterizedRosterCodecError("placeholder departure count must be positive")
    return PlaceholderDeparture(
        ship_class=_require_ship_class(payload.get("shipClass")),
        count=count,
        counterparty_player_id=_optional_int(
            payload.get("counterpartyPlayerId"),
            "placeholder departure.counterpartyPlayerId",
        ),
    )


def placeholder_build_to_json(build: PlaceholderBuild) -> dict[str, object]:
    """Serialize a lattice-signature build. Wire keys match ``placeholders[]`` builds."""
    payload: dict[str, object] = {
        "id": build.id,
        "hullId": build.hull_id,
        "count": build.count,
        "buildSlotUsage": build.build_slot_usage,
    }
    if build.military_score_delta_2x_min is not None:
        payload["militaryScoreDelta2xMin"] = build.military_score_delta_2x_min
    if build.military_score_delta_2x_max is not None:
        payload["militaryScoreDelta2xMax"] = build.military_score_delta_2x_max
    return payload


def placeholder_build_from_json(data: object) -> PlaceholderBuild:
    payload = _require_object(data, "lattice signature.build")
    build_id = payload.get("id")
    if not isinstance(build_id, str) or not build_id:
        raise UncharacterizedRosterCodecError("lattice signature.build.id must be a string")
    count = _require_int(payload.get("count"), "lattice signature.build.count")
    if count <= 0:
        raise UncharacterizedRosterCodecError("lattice signature.build.count must be positive")
    return PlaceholderBuild(
        id=build_id,
        hull_id=_require_int(payload.get("hullId"), "lattice signature.build.hullId"),
        count=count,
        build_slot_usage=_require_int(
            payload.get("buildSlotUsage"),
            "lattice signature.build.buildSlotUsage",
        ),
        military_score_delta_2x_min=_optional_int(
            payload.get("militaryScoreDelta2xMin"),
            "lattice signature.build.militaryScoreDelta2xMin",
        ),
        military_score_delta_2x_max=_optional_int(
            payload.get("militaryScoreDelta2xMax"),
            "lattice signature.build.militaryScoreDelta2xMax",
        ),
    )


def lattice_signature_to_json(signature: LatticeSignature) -> dict[str, object]:
    """Serialize one idle-dock class pair. No objectiveValue."""
    return {
        "shipClass": signature.ship_class,
        "build": placeholder_build_to_json(signature.build),
        "departure": placeholder_departure_to_json(signature.departure),
    }


def lattice_signature_from_json(data: object) -> LatticeSignature:
    payload = _require_object(data, "lattice signature")
    if "objectiveValue" in payload:
        raise UncharacterizedRosterCodecError("lattice signature must not carry objectiveValue")
    return LatticeSignature(
        ship_class=_require_ship_class(payload.get("shipClass")),
        build=placeholder_build_from_json(payload.get("build")),
        departure=placeholder_departure_from_json(payload.get("departure")),
    )


def exact_set_pin_record_to_json(record: ExactSetPinRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "recordId": record.record_id,
        "disposition": record.disposition,
    }
    if record.counterparty_player_id is not None:
        payload["counterpartyPlayerId"] = record.counterparty_player_id
    return payload


def exact_set_pin_record_from_json(data: object) -> ExactSetPinRecord:
    payload = _require_object(data, "exact-set pin record")
    disposition = payload.get("disposition")
    if disposition not in ("lost", "traded"):
        raise UncharacterizedRosterCodecError(
            "exact-set pin record.disposition must be lost or traded"
        )
    if disposition == "traded":
        counterparty = _require_int(
            payload.get("counterpartyPlayerId"),
            "exact-set pin record.counterpartyPlayerId",
        )
    else:
        if "counterpartyPlayerId" in payload:
            raise UncharacterizedRosterCodecError(
                "lost exact-set pin record must not carry counterpartyPlayerId"
            )
        counterparty = None
    return ExactSetPinRecord(
        record_id=_require_str(payload.get("recordId"), "exact-set pin record.recordId"),
        disposition=disposition,
        counterparty_player_id=counterparty,
    )


def exact_set_departure_pin_to_json(pin: ExactSetDeparturePin) -> dict[str, object]:
    return {
        "kind": pin.kind,
        "shipClass": pin.ship_class,
        "records": [exact_set_pin_record_to_json(record) for record in pin.records],
    }


def exact_set_departure_pin_from_json(data: object) -> ExactSetDeparturePin:
    payload = _require_object(data, "exact-set departure pin")
    if payload.get("kind") != "exact_set":
        raise UncharacterizedRosterCodecError("exact-set departure pin.kind must be exact_set")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise UncharacterizedRosterCodecError(
            "exact-set departure pin.records must be a non-empty array"
        )
    return ExactSetDeparturePin(
        ship_class=_require_ship_class(payload.get("shipClass")),
        records=tuple(exact_set_pin_record_from_json(entry) for entry in raw_records),
    )


def departure_pins_to_json(pins: Sequence[ExactSetDeparturePin]) -> list[dict[str, object]]:
    return [exact_set_departure_pin_to_json(pin) for pin in pins]


def departure_pins_from_json(data: object) -> tuple[ExactSetDeparturePin, ...]:
    if not isinstance(data, list):
        raise UncharacterizedRosterCodecError("departurePins must be an array")
    return tuple(exact_set_departure_pin_from_json(entry) for entry in data)


def _require_object(data: object, label: str) -> dict[str, object]:
    if not isinstance(data, dict):
        raise UncharacterizedRosterCodecError(f"{label} must be an object")
    return data


def _require_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UncharacterizedRosterCodecError(f"{label} must be an integer")
    return value


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, label)


def _require_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise UncharacterizedRosterCodecError(f"{label} must be a string")
    return value


def _require_ship_class(value: object) -> FleetShipClass:
    if value not in _VALID_SHIP_CLASSES:
        raise UncharacterizedRosterCodecError("shipClass must be warship or freighter")
    return value
