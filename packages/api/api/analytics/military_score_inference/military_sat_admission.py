"""SAT admission for pinned vs uncharacterized departure.

Refuse military SAT when a departure pin fails on a class that can move
military, when an unknown-class outgoing pairing leave is unpinned, or when
a count-lattice idle-dock event has unknown class. Pin absence on a class
that did not drop is not a fail. A pinned idle-dock class is unchanged
unless a pin already fails. True-freighter unpin still admits SAT. Case-2
emit (placeholders, leftover, lattice signatures) is
``uncharacterized_roster``. Persist of that status is phase 4.
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
    CountLatticeClassEvent,
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
    uncharacterized_roster_result_from_pairing,
)
from api.models.components import Hull
from api.models.game import TurnInfo
from api.models.ship import Ship

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


def _is_unknown_class_idle_dock(event: CountLatticeClassEvent) -> bool:
    """True when idle-dock class is unpinned and can move military."""
    return (
        event.source == "idle_dock"
        and event.ship_class is None
        and class_can_move_military(event.ship_class)
    )


def military_sat_admission(
    signal: CountLatticeSignal,
    pins: tuple[DeparturePin, ...],
    pairing: PublicScoreboardPairing,
) -> MilitarySatAdmission:
    """Admit SAT unless a military-moving class is unpinned.

    Pin fail on a class that can move military refuses. Unknown class
    (``ship_class is None``) on an idle-dock signal or an outgoing pairing
    leave also refuses. Pin absence on a class that did not drop is not a
    fail. Unique-fill and prior-fleet decrease candidates are not this gate.
    A pinned idle-dock class is unchanged unless a pin already fails.
    """
    for pin in pins:
        if pin.kind == "fail" and class_can_move_military(pin.ship_class):
            return MilitarySatAdmission(
                admitted=False,
                signal=signal,
                pins=pins,
                refused_class=pin.ship_class,
            )
    if any(_is_unknown_class_idle_dock(event) for event in signal.events):
        return MilitarySatAdmission(
            admitted=False,
            signal=signal,
            pins=pins,
            refused_class=None,
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


def _pairing_and_idle_dock_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
) -> tuple[PublicScoreboardPairing, TransferBudget | None]:
    """Classify this row's pairing and idle-dock budget from the turn snapshot."""
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
    return pairing, idle_dock


def military_sat_refusal_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    prior_fleet_records: tuple[FleetShipRecord, ...] = (),
) -> InferenceResult | None:
    """Case-2 emit when SAT is refused, or None when SAT may run."""
    pairing, idle_dock = _pairing_and_idle_dock_from_turn(observation, turn)
    admission = resolve_military_sat_admission(
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
    if admission.admitted:
        return None
    return uncharacterized_roster_result_from_pairing(
        observation,
        pairing,
        idle_dock,
        turn,
        prior_fleet_records,
        diagnostics={
            "reason": MILITARY_SAT_REFUSED_REASON,
            "satAdmitted": False,
        },
    )
