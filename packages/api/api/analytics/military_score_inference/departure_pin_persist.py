"""Exact-set departure pin persist records for fleet@T retirement.

Spec-only pins omit a record-id list. Unique-fill is not a pin.
Contract: design-military-score-build-inference.md §3.12.
"""

from __future__ import annotations

from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipClass, FleetShipRecord
from api.analytics.military_score_inference.count_lattice import DeparturePin
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardPairing,
)
from api.models.game import TurnInfo


def persistable_departure_pins(
    pins: tuple[DeparturePin, ...],
    pairing: PublicScoreboardPairing,
) -> list[dict[str, object]]:
    """Named exact-set record ids plus lost vs traded for scores persist.

    Spec-only and fail pins omit the retirement list. Gift/trade pairing
    consumes named ids first (with counterparty); unmatched class drop is lost.
    """
    payload: list[dict[str, object]] = []
    for pin in pins:
        if pin.kind != "exact_set" or not pin.record_ids:
            continue
        payload.append(
            {
                "kind": "exact_set",
                "shipClass": pin.ship_class,
                "records": _retirements_for_class(pin.ship_class, pin.record_ids, pairing),
            }
        )
    return payload


def _retirements_for_class(
    ship_class: FleetShipClass,
    record_ids: tuple[str, ...],
    pairing: PublicScoreboardPairing,
) -> list[dict[str, object]]:
    traded_counterparties = _traded_counterparties(ship_class, pairing)
    records: list[dict[str, object]] = []
    remaining_traded = list(traded_counterparties)
    for record_id in record_ids:
        if remaining_traded:
            counterparty = remaining_traded.pop(0)
            records.append(
                {
                    "recordId": record_id,
                    "disposition": "traded",
                    "counterpartyPlayerId": counterparty,
                }
            )
            continue
        records.append({"recordId": record_id, "disposition": "lost"})
    return records


def _traded_counterparties(
    ship_class: FleetShipClass,
    pairing: PublicScoreboardPairing,
) -> list[int]:
    counterparties: list[int] = []
    for match in pairing.matches:
        if match.family not in ("gift", "trade"):
            continue
        class_delta = match.warship_delta if ship_class == "warship" else match.freighter_delta
        count = -class_delta if class_delta < 0 else 0
        counterparties.extend([match.counterparty_player_id] * count)
    return counterparties


def persistable_departure_pins_from_turn(
    observation: InferenceObservation,
    turn: TurnInfo,
    prior_fleet_records: tuple[FleetShipRecord, ...] = (),
) -> list[dict[str, object]]:
    """Exact-set pin persist records for a SAT-admitted row, or empty."""
    from api.analytics.military_score_inference.military_sat_admission import (
        pairing_and_idle_dock_from_turn,
        resolve_military_sat_admission,
    )

    pairing, idle_dock = pairing_and_idle_dock_from_turn(observation, turn)
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
    return persistable_departure_pins(admission.pins, pairing)
