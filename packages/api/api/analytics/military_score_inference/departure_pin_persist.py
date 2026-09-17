"""Exact-set departure pin persist records for fleet@T retirement.

Spec-only pins omit a record-id list. Unique-fill is not a pin.
Contract: design-military-score-build-inference.md §3.12.
"""

from __future__ import annotations

from api.analytics.fleet.types import FleetShipClass
from api.analytics.military_score_inference.count_lattice import DeparturePin
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardPairing,
)
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    ExactSetDeparturePin,
    ExactSetPinRecord,
)


def persistable_departure_pins(
    pins: tuple[DeparturePin, ...],
    pairing: PublicScoreboardPairing,
) -> tuple[ExactSetDeparturePin, ...]:
    """Named exact-set record ids plus lost vs traded for scores persist.

    Spec-only and fail pins omit the retirement list. Gift/trade pairing
    consumes named ids first (with counterparty); unmatched class drop is lost.

    Gift/trade counterparties for a class come from ``pairing.matches`` in match
    order (gift/trade families only), repeated by that class's outgoing count.
    They are assigned in that order to ``pin.record_ids``, which is remainder-set
    order after alibi cull (prior-ledger records still in the class, in ledger
    order). The first N named ids are traded; any remaining named ids are lost.
    Assignment is FIFO on those two sequences, not hull matching.
    """
    exact_set_pins: list[ExactSetDeparturePin] = []
    for pin in pins:
        if pin.kind != "exact_set" or not pin.record_ids:
            continue
        exact_set_pins.append(
            ExactSetDeparturePin(
                ship_class=pin.ship_class,
                records=_retirements_for_class(pin.ship_class, pin.record_ids, pairing),
            )
        )
    return tuple(exact_set_pins)


def _retirements_for_class(
    ship_class: FleetShipClass,
    record_ids: tuple[str, ...],
    pairing: PublicScoreboardPairing,
) -> tuple[ExactSetPinRecord, ...]:
    remaining_traded = _traded_counterparties(ship_class, pairing)
    records: list[ExactSetPinRecord] = []
    for record_id in record_ids:
        if remaining_traded:
            counterparty = remaining_traded.pop(0)
            records.append(
                ExactSetPinRecord(
                    record_id=record_id,
                    disposition="traded",
                    counterparty_player_id=counterparty,
                )
            )
            continue
        records.append(ExactSetPinRecord(record_id=record_id, disposition="lost"))
    return tuple(records)


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
