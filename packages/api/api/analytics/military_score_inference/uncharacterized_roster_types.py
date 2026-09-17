"""Domain types for leftover, departures, lattice signatures, and exact-set pins.

Codecs live in ``api.serialization.uncharacterized_roster``. This module must
not import serialization, case-2 emit, or pin persist conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.analytics.fleet.types import FleetShipClass

DeparturePinDisposition = Literal["lost", "traded"]


@dataclass(frozen=True)
class PointLeftover:
    """Today's point leftover (not the refused-SAT warship path)."""

    unexplained_military_delta_2x: int
    kind: Literal["point"] = "point"


@dataclass(frozen=True)
class UnknownLossBoundLeftover:
    """Lower bound on unexplained military when lost construction is unknown."""

    lower_bound_2x: int
    kind: Literal["unknown_loss_bound"] = "unknown_loss_bound"


UnknownLossLeftover = PointLeftover | UnknownLossBoundLeftover


@dataclass(frozen=True)
class PlaceholderDeparture:
    """Class-tagged unexplained departure. Sign lives in the type, not hull -1."""

    ship_class: FleetShipClass
    count: int
    counterparty_player_id: int | None = None


@dataclass(frozen=True)
class PlaceholderBuild:
    """Unknown-military or generic-freighter build on a lattice signature."""

    id: str
    hull_id: int
    count: int
    build_slot_usage: int
    military_score_delta_2x_min: int | None = None
    military_score_delta_2x_max: int | None = None


@dataclass(frozen=True)
class LatticeSignature:
    """One idle-dock class alternative: hidden build plus placeholder departure."""

    ship_class: FleetShipClass
    build: PlaceholderBuild
    departure: PlaceholderDeparture


@dataclass(frozen=True)
class ExactSetPinRecord:
    """One named exact-set retirement for fleet@T."""

    record_id: str
    disposition: DeparturePinDisposition
    counterparty_player_id: int | None = None


@dataclass(frozen=True)
class ExactSetDeparturePin:
    """Exact-set persist pin: named record ids plus lost vs traded."""

    ship_class: FleetShipClass
    records: tuple[ExactSetPinRecord, ...]
    kind: Literal["exact_set"] = "exact_set"
