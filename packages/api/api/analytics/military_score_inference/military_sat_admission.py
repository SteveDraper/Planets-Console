"""SAT admission for pinned vs uncharacterized departure.

Refuse military SAT when a departure pin fails on a class that can move
military, or when an unknown-class outgoing pairing leave is unpinned.
Pin absence on a class that did not drop is not a fail. True-freighter
unpin still admits SAT. Case-2 emit (placeholders, leftover, lattice
signatures) is ``uncharacterized_roster``. Persist of that status is phase 4.
Contract: design-military-score-build-inference.md §3.12.
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
    PairingMatch,
    PublicScoreboardPairing,
    TransferBudget,
    classify_public_scoreboard_pairing,
    public_scoreboard_row_from_observation,
    transfer_budget_for_row,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    public_scoreboard_rows_from_scores,
)
from api.analytics.military_score_inference.uncharacterized_roster import (
    STATUS_UNCHARACTERIZED_ROSTER,
    UNCHARACTERIZED_ROSTER_SUMMARY,
    uncharacterized_roster_result_from_turn,
)
from api.models.components import Hull
from api.models.game import TurnInfo
from api.models.ship import Ship

STATUS_MILITARY_SAT_REFUSED = STATUS_UNCHARACTERIZED_ROSTER
MILITARY_SAT_REFUSED_SUMMARY = UNCHARACTERIZED_ROSTER_SUMMARY
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


def _is_unknown_class_outgoing_leave(match: PairingMatch) -> bool:
    """True for a PP-gap gift whose hull class is not pinned on either column."""
    return match.family == "gift" and match.is_unpinned_class_choice()


def military_sat_admission(
    signal: CountLatticeSignal,
    pins: tuple[DeparturePin, ...],
    pairing: PublicScoreboardPairing,
) -> MilitarySatAdmission:
    """Admit SAT unless a warship pin failed or an unknown-class outgoing leave is unpinned.

    ``CountLatticeClassEvent`` has no direction or family; it is not this
    iterator. Pin absence on a class that did not drop is not a fail.
    Unique-fill and prior-fleet decrease candidates are not this gate.
    Idle-dock PP events are not this refuse: ``departure_pin`` is scoreboard
    class-drop only, and hidden arrivals are what SAT explains.
    """
    for pin in pins:
        if pin.kind == "fail" and class_can_move_military(pin.ship_class):
            return MilitarySatAdmission(
                admitted=False,
                signal=signal,
                pins=pins,
                refused_class=pin.ship_class,
            )
    if any(_is_unknown_class_outgoing_leave(match) for match in pairing.matches):
        return MilitarySatAdmission(
            admitted=False,
            signal=signal,
            pins=pins,
            refused_class=None,
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
    return military_sat_admission(signal, pins, pairing)


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
    """Admission-only refuse shell. None when SAT may run.

    Turn-scoped emit (placeholders, leftover, lattice signatures) is
    ``military_sat_refusal_from_turn``. Not a persistable product status.
    """
    if admission.admitted:
        return None
    return InferenceResult(
        status=STATUS_UNCHARACTERIZED_ROSTER,
        solutions=(),
        diagnostics={
            "reason": MILITARY_SAT_REFUSED_REASON,
            "satAdmitted": False,
        },
    )


def military_sat_refusal_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    prior_fleet_records: tuple[FleetShipRecord, ...] = (),
) -> InferenceResult | None:
    """Case-2 emit when SAT is refused, or None when SAT may run."""
    admission = resolve_military_sat_admission_from_turn(
        observation,
        turn,
        prior_fleet_records,
    )
    if admission.admitted:
        return None
    return uncharacterized_roster_result_from_turn(
        observation,
        turn,
        prior_fleet_records,
        diagnostics={
            "reason": MILITARY_SAT_REFUSED_REASON,
            "satAdmitted": False,
        },
    )
