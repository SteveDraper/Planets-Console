"""SAT admission for pinned vs uncharacterized departure.

Refuse military SAT when a count-lattice signal has no departure pin on a
class that can move military. True-freighter unpin still admits SAT.
Does not emit placeholders or persist ``uncharacterized_roster`` (phase 3).
Contract: design-military-score-build-inference.md §3.12; ticket #487.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetShipClass,
    FleetShipRecord,
)
from api.analytics.military_score_inference.count_lattice import (
    CountLatticeSignal,
    DeparturePin,
    count_lattice_signal,
    departure_pin,
)
from api.analytics.military_score_inference.models import InferenceObservation, InferenceResult
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardPairing,
    TransferBudget,
    classify_public_scoreboard_pairing,
    public_scoreboard_row_from_observation,
    transfer_budget_for_row,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    public_scoreboard_rows_from_scores,
)
from api.models.components import Hull
from api.models.game import TurnInfo
from api.models.ship import Ship

STATUS_MILITARY_SAT_REFUSED = "military_sat_refused"
MILITARY_SAT_REFUSED_SUMMARY = "Unpinned military departure; military SAT not entered"
MILITARY_SAT_REFUSED_REASON = "unpinned_military_departure"


@dataclass(frozen=True)
class MilitarySatAdmission:
    """Whether ``tier_solve`` may build a military catalog and run CP-SAT."""

    admitted: bool
    signal: CountLatticeSignal
    pins: tuple[DeparturePin, ...]
    refused_class: FleetShipClass | None = None


def class_can_move_military(ship_class: FleetShipClass | None) -> bool:
    """True for warships and unknown class; false for true-freighter."""
    return ship_class != "freighter"


def pin_holds(pin: DeparturePin | None) -> bool:
    return pin is not None and pin.kind in ("exact_set", "spec_only")


def military_sat_admission(
    signal: CountLatticeSignal,
    pins: tuple[DeparturePin, ...],
) -> MilitarySatAdmission:
    """Admit SAT unless a scoreboard leave-signal on a military-moving class is unpinned.

    Unique-fill and prior-fleet decrease candidates are not this gate.
    Idle-dock PP events are not this refuse: ``departure_pin`` is scoreboard
    class-drop only, and hidden arrivals are what SAT explains.
    """
    pin_by_class = {pin.ship_class: pin for pin in pins}
    for event in signal.events:
        if event.source not in ("unmatched_drop", "pairing"):
            continue
        if not class_can_move_military(event.ship_class):
            continue
        if event.ship_class is None or not pin_holds(pin_by_class.get(event.ship_class)):
            return MilitarySatAdmission(
                admitted=False,
                signal=signal,
                pins=pins,
                refused_class=event.ship_class,
            )
    return MilitarySatAdmission(admitted=True, signal=signal, pins=pins)


def resolve_military_sat_admission(
    observation: InferenceObservation,
    *,
    pairing: PublicScoreboardPairing,
    idle_dock: TransferBudget | None,
    prior_ledger: FleetAcquisitionLedger,
    this_turn_ships: Sequence[Ship],
    hulls_by_id: dict[int, Hull],
) -> MilitarySatAdmission:
    signal = count_lattice_signal(observation, pairing, idle_dock)
    pins = departure_pin(
        observation,
        prior_ledger,
        this_turn_ships,
        hulls_by_id=hulls_by_id,
    )
    return military_sat_admission(signal, pins)


def resolve_military_sat_admission_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    prior_fleet_records: tuple[FleetShipRecord, ...] = (),
) -> MilitarySatAdmission:
    this_row = public_scoreboard_row_from_observation(observation)
    pairing = classify_public_scoreboard_pairing(
        this_row,
        public_scoreboard_rows_from_scores(turn.scores, this_player_id=observation.player_id),
        settings=turn.settings,
        is_after_ship_limit=observation.is_after_ship_limit,
    )
    idle_dock = transfer_budget_for_row(
        this_row,
        settings=turn.settings,
        is_after_ship_limit=observation.is_after_ship_limit,
    )
    return resolve_military_sat_admission(
        observation,
        pairing=pairing,
        idle_dock=idle_dock,
        prior_ledger=FleetAcquisitionLedger(
            player_id=observation.player_id,
            records=list(prior_fleet_records),
        ),
        this_turn_ships=turn.ships,
        hulls_by_id={hull.id: hull for hull in turn.hulls},
    )


def military_sat_refusal_result(
    admission: MilitarySatAdmission,
) -> InferenceResult | None:
    """In-memory skip when SAT is refused. None when SAT may run.

    Not a persistable product status. Phase 3 turns this into
    ``uncharacterized_roster``.
    """
    if admission.admitted:
        return None
    return InferenceResult(
        status=STATUS_MILITARY_SAT_REFUSED,
        solutions=(),
        diagnostics={
            "reason": MILITARY_SAT_REFUSED_REASON,
            "satAdmitted": False,
        },
    )
