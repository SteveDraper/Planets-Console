"""Codecs for uncharacterized-roster leftover, departures, and lattice signatures.

Phase 3 introduces the in-memory / live-payload shape. Durable persist of these
fields is phase 4 -- do not encode an unknown-loss bound as a point
``unexplainedMilitaryDelta2x``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.fleet.types import FleetShipClass
from api.errors import CoreAPIError

if TYPE_CHECKING:
    from api.analytics.military_score_inference.uncharacterized_roster import (
        LatticeSignature,
        PlaceholderDeparture,
        UnknownLossLeftover,
    )

LEFTOVER_KIND_POINT = "point"
LEFTOVER_KIND_UNKNOWN_LOSS_BOUND = "unknown_loss_bound"
PLACEHOLDER_DEPARTURE_ID = "placeholder_departure"
_VALID_SHIP_CLASSES = frozenset({"warship", "freighter"})


class UncharacterizedRosterCodecError(CoreAPIError):
    """Malformed leftover, departure, or lattice-signature payload."""

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
    from api.analytics.military_score_inference.uncharacterized_roster import (
        PointLeftover,
        UnknownLossBoundLeftover,
    )

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
    from api.analytics.military_score_inference.uncharacterized_roster import PlaceholderDeparture

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


def lattice_signature_to_json(signature: LatticeSignature) -> dict[str, object]:
    """Serialize one idle-dock class pair. No objectiveValue."""
    payload: dict[str, object] = {
        "shipClass": signature.ship_class,
        "build": dict(signature.build),
        "departure": placeholder_departure_to_json(signature.departure),
    }
    return payload


def lattice_signature_from_json(data: object) -> LatticeSignature:
    from api.analytics.military_score_inference.uncharacterized_roster import LatticeSignature

    payload = _require_object(data, "lattice signature")
    if "objectiveValue" in payload:
        raise UncharacterizedRosterCodecError("lattice signature must not carry objectiveValue")
    build = payload.get("build")
    if not isinstance(build, dict):
        raise UncharacterizedRosterCodecError("lattice signature.build must be an object")
    return LatticeSignature(
        ship_class=_require_ship_class(payload.get("shipClass")),
        build=dict(build),
        departure=placeholder_departure_from_json(payload.get("departure")),
    )


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


def _require_ship_class(value: object) -> FleetShipClass:
    if value not in _VALID_SHIP_CLASSES:
        raise UncharacterizedRosterCodecError("shipClass must be warship or freighter")
    return value
