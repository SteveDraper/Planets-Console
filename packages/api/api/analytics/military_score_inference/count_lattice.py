"""Count-lattice signal and departure pin for pinned vs uncharacterized departure.

Pure determination: does not admit SAT, persist, or retire fleet rows.
Contract: design-military-score-build-inference.md §3.12.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from api.analytics.fleet.field_constraints import (
    known_non_negative_component_id,
    known_positive_component_id,
    known_ship_id_value,
)
from api.analytics.fleet.ship_class import record_ship_class
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetShipClass,
    FleetShipRecord,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardPairing,
    TransferBudget,
    public_scoreboard_row_from_observation,
    unique_incoming_class,
)
from api.models.components import Hull
from api.models.ship import Ship

CountLatticeEventSource = Literal["unmatched_drop", "pairing", "idle_dock"]
DeparturePinKind = Literal["fail", "exact_set", "spec_only"]


@dataclass(frozen=True)
class CountLatticeClassEvent:
    ship_class: FleetShipClass | None
    source: CountLatticeEventSource
    count: int


@dataclass(frozen=True)
class CountLatticeSignal:
    events: tuple[CountLatticeClassEvent, ...]

    def __bool__(self) -> bool:
        return bool(self.events)


@dataclass(frozen=True)
class DeparturePin:
    kind: DeparturePinKind
    ship_class: FleetShipClass
    record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassRemainderSet:
    ship_class: FleetShipClass
    remainders: tuple[FleetShipRecord, ...]
    drop: int


def count_lattice_signal(
    observation: InferenceObservation,
    pairing: PublicScoreboardPairing,
    idle_dock: TransferBudget | None,
) -> CountLatticeSignal:
    """Return class-wise roster-change events from pairing and the PP lattice.

    Unique-fill and prior-fleet decrease candidates are not inputs.
    """
    events: list[CountLatticeClassEvent] = []
    if pairing.unmatched_warship_drop > 0:
        events.append(
            CountLatticeClassEvent(
                ship_class="warship",
                source="unmatched_drop",
                count=pairing.unmatched_warship_drop,
            )
        )
    if pairing.unmatched_freighter_drop > 0:
        events.append(
            CountLatticeClassEvent(
                ship_class="freighter",
                source="unmatched_drop",
                count=pairing.unmatched_freighter_drop,
            )
        )
    for match in pairing.matches:
        if match.is_unpinned_class_choice():
            events.append(
                CountLatticeClassEvent(
                    ship_class=None,
                    source="pairing",
                    count=match.transfer_count,
                )
            )
            continue
        if match.warship_delta != 0:
            events.append(
                CountLatticeClassEvent(
                    ship_class="warship",
                    source="pairing",
                    count=abs(match.warship_delta),
                )
            )
        if match.freighter_delta != 0:
            events.append(
                CountLatticeClassEvent(
                    ship_class="freighter",
                    source="pairing",
                    count=abs(match.freighter_delta),
                )
            )
        if match.family == "trade" and match.warship_delta == 0 and match.freighter_delta == 0:
            events.append(CountLatticeClassEvent(ship_class=None, source="pairing", count=1))
    if idle_dock is not None:
        pinned_class = unique_incoming_class(public_scoreboard_row_from_observation(observation))
        if idle_dock.excess_out > 0:
            events.append(
                CountLatticeClassEvent(
                    ship_class=pinned_class,
                    source="idle_dock",
                    count=idle_dock.excess_out,
                )
            )
        if idle_dock.excess_in > 0:
            events.append(
                CountLatticeClassEvent(
                    ship_class=pinned_class,
                    source="idle_dock",
                    count=idle_dock.excess_in,
                )
            )
    return CountLatticeSignal(events=tuple(events))


def record_has_known_spec(record: FleetShipRecord) -> bool:
    """True when hull and mounts are FleetFieldKnown, not option-set unique-fill."""
    return _known_spec_key(record) is not None


def departure_pin(
    observation: InferenceObservation,
    prior_ledger: FleetAcquisitionLedger,
    this_turn_ships: Sequence[Ship],
    *,
    hulls_by_id: dict[int, Hull],
) -> tuple[DeparturePin, ...]:
    """Pin remaining same-class rows after fleet-alibi cull, or fail that class.

    One result per class with drop D > 0: fail, exact-set, or spec-only.
    Omit a class when D <= 0 (no departure to pin). Exact-set names
    ``record_id``s. Spec-only and fail do not. Unique-fill is not a pin.
    """
    remainder_sets = _remainder_sets_after_alibi(
        observation.player_id,
        prior_ledger,
        this_turn_ships,
        class_drops_from_observation(observation),
        hulls_by_id=hulls_by_id,
    )
    pins: list[DeparturePin] = []
    for remainder_set in remainder_sets:
        pin = _pin_class(remainder_set)
        if pin is not None:
            pins.append(pin)
    return tuple(pins)


def class_drops_from_observation(
    observation: InferenceObservation,
) -> dict[FleetShipClass, int]:
    """v1 class drop D: non-negative scoreboard column loss per class."""
    return {
        "warship": max(0, -observation.warship_delta),
        "freighter": max(0, -observation.freighter_delta),
    }


def _alibi_ship_ids(this_turn_ships: Sequence[Ship], player_id: int) -> frozenset[int]:
    return frozenset(
        ship.id for ship in this_turn_ships if ship.ownerid == player_id and ship.id > 0
    )


def _remainder_sets_after_alibi(
    player_id: int,
    prior_ledger: FleetAcquisitionLedger,
    this_turn_ships: Sequence[Ship],
    class_drops: Mapping[FleetShipClass, int],
    *,
    hulls_by_id: dict[int, Hull],
) -> tuple[ClassRemainderSet, ...]:
    alibi_ids = _alibi_ship_ids(this_turn_ships, player_id)
    remainders_by_class: dict[FleetShipClass, list[FleetShipRecord]] = {
        "warship": [],
        "freighter": [],
    }
    for record in prior_ledger.records:
        if record.disposition != "active":
            continue
        ship_id = known_ship_id_value(record)
        if ship_id is not None and ship_id in alibi_ids:
            continue
        ship_class = record_ship_class(record, hulls_by_id)
        if ship_class is None:
            continue
        remainders_by_class[ship_class].append(record)
    return tuple(
        ClassRemainderSet(
            ship_class=ship_class,
            remainders=tuple(remainders),
            drop=class_drops[ship_class],
        )
        for ship_class, remainders in remainders_by_class.items()
    )


def _pin_class(remainder_set: ClassRemainderSet) -> DeparturePin | None:
    drop = remainder_set.drop
    if drop <= 0:
        return None
    remainders = remainder_set.remainders
    ship_class = remainder_set.ship_class
    spec_keys = [_known_spec_key(record) for record in remainders]
    if any(spec_key is None for spec_key in spec_keys):
        return DeparturePin(kind="fail", ship_class=ship_class)
    if len(remainders) == drop:
        return DeparturePin(
            kind="exact_set",
            ship_class=ship_class,
            record_ids=tuple(record.record_id for record in remainders),
        )
    if len(remainders) > drop and len(set(spec_keys)) == 1:
        return DeparturePin(kind="spec_only", ship_class=ship_class)
    return DeparturePin(kind="fail", ship_class=ship_class)


def _known_spec_key(record: FleetShipRecord) -> tuple[int, int, int, int] | None:
    hull_id = known_positive_component_id(record.fields.hull)
    engine_id = known_positive_component_id(record.fields.engine)
    beam_id = known_non_negative_component_id(record.fields.beams)
    launcher_id = known_non_negative_component_id(record.fields.launchers)
    if hull_id is None or engine_id is None or beam_id is None or launcher_id is None:
        return None
    return hull_id, engine_id, beam_id, launcher_id
