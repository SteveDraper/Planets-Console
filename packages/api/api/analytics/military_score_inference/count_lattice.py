"""Count-lattice signal and departure pin for pinned vs uncharacterized departure.

Pure determination: does not admit SAT, persist, or retire fleet rows.
Contract: design-military-score-build-inference.md §3.12.
"""

from __future__ import annotations

from collections.abc import Sequence
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
DeparturePinKind = Literal["exact_set", "spec_only"]


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

    Exact-set names ``record_id``s. Spec-only does not. Unique-fill is not a pin.
    """
    alibi_ids = _alibi_ship_ids(this_turn_ships, observation.player_id)
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
    pins: list[DeparturePin] = []
    for ship_class, remainders in remainders_by_class.items():
        pin = _pin_class(
            ship_class,
            remainders,
            _class_drop(observation, ship_class),
        )
        if pin is not None:
            pins.append(pin)
    return tuple(pins)


def _alibi_ship_ids(this_turn_ships: Sequence[Ship], player_id: int) -> frozenset[int]:
    return frozenset(
        ship.id for ship in this_turn_ships if ship.ownerid == player_id and ship.id > 0
    )


def _class_drop(observation: InferenceObservation, ship_class: FleetShipClass) -> int:
    if ship_class == "warship":
        return max(0, -observation.warship_delta)
    return max(0, -observation.freighter_delta)


def _pin_class(
    ship_class: FleetShipClass,
    remainders: list[FleetShipRecord],
    drop: int,
) -> DeparturePin | None:
    if drop <= 0:
        return None
    spec_keys = [_known_spec_key(record) for record in remainders]
    if any(spec_key is None for spec_key in spec_keys):
        return None
    if len(remainders) == drop:
        return DeparturePin(
            kind="exact_set",
            ship_class=ship_class,
            record_ids=tuple(record.record_id for record in remainders),
        )
    if len(remainders) > drop and len(set(spec_keys)) == 1:
        return DeparturePin(kind="spec_only", ship_class=ship_class)
    return None


def _known_spec_key(record: FleetShipRecord) -> tuple[int, int, int, int] | None:
    hull_id = known_positive_component_id(record.fields.hull)
    engine_id = known_positive_component_id(record.fields.engine)
    beam_id = known_non_negative_component_id(record.fields.beams)
    launcher_id = known_non_negative_component_id(record.fields.launchers)
    if hull_id is None or engine_id is None or beam_id is None or launcher_id is None:
        return None
    return hull_id, engine_id, beam_id, launcher_id
