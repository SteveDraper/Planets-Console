"""Catalog actions for ship loss, gift, trade, and acquired ship.

Departures are prior-fleet decrease candidates, not inverted ship-build combos.
Families are ranked ``solutions[]`` actions with counterparty player id when
pairing pins a row. Admitted from the first ship-bearing cheap step (not via
tier aggregate allowlist).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from api.analytics.fleet.types import FleetShipClass, FleetShipRecord
from api.analytics.military_score_inference.models import CandidateAction, InferenceObservation
from api.analytics.military_score_inference.prior_fleet_decrease_candidates import (
    PriorFleetDecreaseCandidate,
    decrease_capacity_by_class,
    prior_fleet_decrease_candidates,
)
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardPairing,
    PublicScoreboardRow,
    classify_public_scoreboard_pairing,
    public_scoreboard_row_from_observation,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.player import Score

SHIP_LOSS_ACTION_PREFIX = "ship_loss:"
GIFT_ACTION_PREFIX = "gift:"
TRADE_ACTION_PREFIX = "trade:"
ACQUIRED_SHIP_ACTION_PREFIX = "acquired:"


def public_scoreboard_rows_from_scores(
    scores: tuple[Score, ...] | list[Score],
    *,
    this_player_id: int,
) -> tuple[PublicScoreboardRow, ...]:
    return tuple(
        PublicScoreboardRow(
            player_id=score.ownerid,
            warship_delta=score.shipchange,
            freighter_delta=score.freighterchange,
            military_delta_2x=2 * score.militarychange,
        )
        for score in scores
        if score.ownerid != this_player_id
    )


@dataclass(frozen=True)
class ShipTransferCatalogFragment:
    """Transfer actions plus combo/departure caps from one pairing."""

    actions: tuple[CandidateAction, ...]
    extra_warship_capacity: int
    extra_freighter_capacity: int
    reserved_incoming_warships: int
    reserved_incoming_freighters: int
    prior_warship_departure_cap: int
    prior_freighter_departure_cap: int
    prior_departure_group_caps: dict[str, int]


def ship_transfer_combo_capacity(
    observation: InferenceObservation,
    pairing: PublicScoreboardPairing,
    candidates: tuple[PriorFleetDecreaseCandidate, ...],
) -> tuple[int, int, int, int]:
    """Warship/freighter extra combo capacity and reserved incoming acquired counts.

    Extra combo slots are prior-fleet departures when the class did not grow, so
    loss+replace (net 0) can still build. Incoming acquired counts are reserved
    out of the build bound so they are not explained as ship-build combos.
    """
    extra_warship, extra_freighter = decrease_capacity_by_class(candidates)
    if observation.warship_delta > 0:
        extra_warship = 0
    if observation.freighter_delta > 0:
        extra_freighter = 0
    reserved_warship = sum(
        match.warship_delta for match in pairing.matches if match.family == "acquired"
    )
    reserved_freighter = sum(
        match.freighter_delta for match in pairing.matches if match.family == "acquired"
    )
    return extra_warship, extra_freighter, reserved_warship, reserved_freighter


def build_ship_transfer_catalog_fragment(
    observation: InferenceObservation,
    *,
    peer_rows: tuple[PublicScoreboardRow, ...],
    prior_fleet_records: tuple[FleetShipRecord, ...],
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
) -> ShipTransferCatalogFragment:
    """Admit transfer actions and combo/departure caps from one pairing."""
    pairing = classify_public_scoreboard_pairing(
        public_scoreboard_row_from_observation(observation),
        peer_rows,
    )
    candidates = prior_fleet_decrease_candidates(
        prior_fleet_records,
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
    )
    actions: list[CandidateAction] = []
    actions.extend(_loss_actions(observation, pairing, candidates))
    actions.extend(_gift_actions(pairing, candidates))
    actions.extend(_trade_actions(pairing, candidates, observation))
    actions.extend(_acquired_actions(pairing))
    extra_warship, extra_freighter, reserved_warship, reserved_freighter = (
        ship_transfer_combo_capacity(observation, pairing, candidates)
    )
    prior_warship_departure_cap, prior_freighter_departure_cap = decrease_capacity_by_class(
        candidates
    )
    return ShipTransferCatalogFragment(
        actions=tuple(action for action in actions if action.upper_bound > 0),
        extra_warship_capacity=extra_warship,
        extra_freighter_capacity=extra_freighter,
        reserved_incoming_warships=reserved_warship,
        reserved_incoming_freighters=reserved_freighter,
        prior_warship_departure_cap=prior_warship_departure_cap,
        prior_freighter_departure_cap=prior_freighter_departure_cap,
        prior_departure_group_caps=_prior_departure_group_caps(candidates),
    )


def _prior_departure_group_caps(
    candidates: tuple[PriorFleetDecreaseCandidate, ...],
) -> dict[str, int]:
    """Record count per departure group, shared across loss/gift/trade families."""
    return {
        _prior_group_key(ship_class, kind, min_2x, max_2x): len(group)
        for ship_class in ("warship", "freighter")
        for (kind, min_2x, max_2x), group in _group_candidates(candidates, ship_class).items()
    }


def _group_candidates(
    candidates: tuple[PriorFleetDecreaseCandidate, ...],
    ship_class: FleetShipClass,
) -> dict[tuple[str, int, int], list[PriorFleetDecreaseCandidate]]:
    grouped: dict[tuple[str, int, int], list[PriorFleetDecreaseCandidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.ship_class != ship_class:
            continue
        if candidate.is_point_military:
            key = ("point", candidate.score_delta_2x_min, candidate.score_delta_2x_max)
        else:
            key = ("envelope", candidate.score_delta_2x_min, candidate.score_delta_2x_max)
        grouped[key].append(candidate)
    return grouped


def _departure_score_bounds(kind: str, min_2x: int, max_2x: int) -> tuple[int, int, int]:
    """Negate construction military for a departure. Returns point, min, max."""
    if kind == "point":
        point = -min_2x
        return point, point, point
    return 0, -max_2x, -min_2x


def _military_id_suffix(kind: str, min_2x: int, max_2x: int) -> str:
    if kind == "point":
        return f"point:{min_2x}"
    return f"envelope:{min_2x}:{max_2x}"


def _prior_group_key(ship_class: FleetShipClass, kind: str, min_2x: int, max_2x: int) -> str:
    return f"{ship_class}:{_military_id_suffix(kind, min_2x, max_2x)}"


def _departure_action(
    *,
    action_id: str,
    label: str,
    kind: str,
    min_2x: int,
    max_2x: int,
    ship_class: FleetShipClass,
    upper_bound: int,
    counterparty_player_id: int | None = None,
    warship_delta: int | None = None,
    freighter_delta: int | None = None,
    score_point: int | None = None,
    departure_count: int = 1,
) -> CandidateAction:
    """One catalog action departing ``departure_count`` records from one group.

    The group key stays per-unit; the military envelope and prior-fleet usage
    scale with the departure count so a multi-ship action prices and consumes
    all of its departing records.
    """
    if score_point is not None:
        point = score_point
        score_min = score_point
        score_max = score_point
        envelope = False
    else:
        point, score_min, score_max = _departure_score_bounds(kind, min_2x, max_2x)
        point *= departure_count
        score_min *= departure_count
        score_max *= departure_count
        envelope = kind == "envelope"
    if warship_delta is None:
        warship_delta = -1 if ship_class == "warship" else 0
    if freighter_delta is None:
        freighter_delta = -1 if ship_class == "freighter" else 0
    return CandidateAction(
        id=action_id,
        label=label,
        score_delta_2x=point,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        score_delta_2x_min=score_min if envelope else None,
        score_delta_2x_max=score_max if envelope else None,
        counterparty_player_id=counterparty_player_id,
        prior_warship_usage=departure_count if ship_class == "warship" else 0,
        prior_freighter_usage=departure_count if ship_class == "freighter" else 0,
        prior_group_key=_prior_group_key(ship_class, kind, min_2x, max_2x),
        upper_bound=upper_bound,
    )


def _loss_actions(
    observation: InferenceObservation,
    pairing: PublicScoreboardPairing,
    candidates: tuple[PriorFleetDecreaseCandidate, ...],
) -> list[CandidateAction]:
    actions: list[CandidateAction] = []
    for ship_class, unmatched, net in (
        ("warship", pairing.unmatched_warship_drop, observation.warship_delta),
        ("freighter", pairing.unmatched_freighter_drop, observation.freighter_delta),
    ):
        if unmatched > 0:
            class_upper = unmatched
        elif net == 0 and not any(match.family == "trade" for match in pairing.matches):
            class_upper = None
        else:
            continue
        grouped = _group_candidates(candidates, ship_class)
        for (kind, min_2x, max_2x), group in grouped.items():
            upper = len(group) if class_upper is None else min(class_upper, len(group))
            if upper <= 0:
                continue
            actions.append(
                _departure_action(
                    action_id=_loss_action_id(ship_class, kind, min_2x, max_2x),
                    label=_loss_label(ship_class, kind, min_2x, max_2x),
                    kind=kind,
                    min_2x=min_2x,
                    max_2x=max_2x,
                    ship_class=ship_class,
                    upper_bound=upper,
                )
            )
    return actions


def _gift_actions(
    pairing: PublicScoreboardPairing,
    candidates: tuple[PriorFleetDecreaseCandidate, ...],
) -> list[CandidateAction]:
    actions: list[CandidateAction] = []
    for match in pairing.matches:
        if match.family != "gift":
            continue
        for ship_class, count_delta in (
            ("warship", match.warship_delta),
            ("freighter", match.freighter_delta),
        ):
            if count_delta >= 0:
                continue
            needed = -count_delta
            grouped = _group_candidates(candidates, ship_class)
            for (kind, min_2x, max_2x), group in grouped.items():
                actions.append(
                    _departure_action(
                        action_id=_gift_action_id(
                            ship_class, match.counterparty_player_id, kind, min_2x, max_2x
                        ),
                        label=_gift_label(ship_class, match.counterparty_player_id),
                        kind=kind,
                        min_2x=min_2x,
                        max_2x=max_2x,
                        ship_class=ship_class,
                        upper_bound=min(needed, len(group)),
                        counterparty_player_id=match.counterparty_player_id,
                    )
                )
    return actions


def _trade_actions(
    pairing: PublicScoreboardPairing,
    candidates: tuple[PriorFleetDecreaseCandidate, ...],
    observation: InferenceObservation,
) -> list[CandidateAction]:
    actions: list[CandidateAction] = []
    for match in pairing.matches:
        if match.family != "trade":
            continue
        same_class_swap = match.warship_delta == 0 and match.freighter_delta == 0
        # A class-flip trade departs all k flipped ships in one action, so its
        # military envelope and prior-fleet usage scale by k. A same-class swap
        # has zero count deltas, so k is unobservable and stays 1.
        if match.warship_delta < 0:
            outgoing_class: FleetShipClass = "warship"
            departing_count = -match.warship_delta
        elif match.freighter_delta < 0:
            outgoing_class = "freighter"
            departing_count = -match.freighter_delta
        elif same_class_swap:
            outgoing_class = "warship"
            departing_count = 1
        else:
            continue
        grouped = _group_candidates(candidates, outgoing_class)
        score_point = observation.military_delta_2x if same_class_swap else None
        for (kind, min_2x, max_2x), group in grouped.items():
            if len(group) < departing_count:
                continue
            actions.append(
                _departure_action(
                    action_id=_trade_action_id(
                        outgoing_class, match.counterparty_player_id, kind, min_2x, max_2x
                    ),
                    label=_trade_label(outgoing_class, match.counterparty_player_id),
                    kind=kind,
                    min_2x=min_2x,
                    max_2x=max_2x,
                    ship_class=outgoing_class,
                    upper_bound=1,
                    counterparty_player_id=match.counterparty_player_id,
                    warship_delta=match.warship_delta,
                    freighter_delta=match.freighter_delta,
                    score_point=score_point,
                    departure_count=departing_count,
                )
            )
    return actions


def _incoming_military_bounds(incoming_military_2x: int) -> tuple[int, int | None, int | None]:
    """Per-unit military for one acquired ship. Returns point, min, max.

    The counterparty's drop is a total over all transferred ships, so each unit
    carries any share of it: an envelope [0, total] admits the true total for
    any incoming count >= 1. A non-positive total stays a point.
    """
    if incoming_military_2x <= 0:
        return incoming_military_2x, None, None
    return 0, 0, incoming_military_2x


def _acquired_actions(pairing: PublicScoreboardPairing) -> list[CandidateAction]:
    actions: list[CandidateAction] = []
    for match in pairing.matches:
        if match.family != "acquired":
            continue
        incoming_military = -match.counterparty_military_delta_2x
        if match.warship_delta > 0:
            point, min_2x, max_2x = _incoming_military_bounds(incoming_military)
            actions.append(
                CandidateAction(
                    id=f"{ACQUIRED_SHIP_ACTION_PREFIX}warship:from:{match.counterparty_player_id}",
                    label=f"Acquired warship from player {match.counterparty_player_id}",
                    score_delta_2x=point,
                    warship_delta=1,
                    score_delta_2x_min=min_2x,
                    score_delta_2x_max=max_2x,
                    counterparty_player_id=match.counterparty_player_id,
                    upper_bound=match.warship_delta,
                )
            )
        if match.freighter_delta > 0:
            freighter_military = 0 if match.warship_delta > 0 else incoming_military
            point, min_2x, max_2x = _incoming_military_bounds(freighter_military)
            actions.append(
                CandidateAction(
                    id=f"{ACQUIRED_SHIP_ACTION_PREFIX}freighter:from:{match.counterparty_player_id}",
                    label=f"Acquired freighter from player {match.counterparty_player_id}",
                    score_delta_2x=point,
                    freighter_delta=1,
                    score_delta_2x_min=min_2x,
                    score_delta_2x_max=max_2x,
                    counterparty_player_id=match.counterparty_player_id,
                    upper_bound=match.freighter_delta,
                )
            )
    return actions


def _loss_action_id(ship_class: FleetShipClass, kind: str, min_2x: int, max_2x: int) -> str:
    return f"{SHIP_LOSS_ACTION_PREFIX}{ship_class}:{_military_id_suffix(kind, min_2x, max_2x)}"


def _gift_action_id(
    ship_class: FleetShipClass,
    player_id: int,
    kind: str,
    min_2x: int,
    max_2x: int,
) -> str:
    return (
        f"{GIFT_ACTION_PREFIX}{ship_class}:to:{player_id}:"
        f"{_military_id_suffix(kind, min_2x, max_2x)}"
    )


def _trade_action_id(
    ship_class: FleetShipClass,
    player_id: int,
    kind: str,
    min_2x: int,
    max_2x: int,
) -> str:
    return (
        f"{TRADE_ACTION_PREFIX}{ship_class}:with:{player_id}:"
        f"{_military_id_suffix(kind, min_2x, max_2x)}"
    )


def _loss_label(ship_class: FleetShipClass, kind: str, min_2x: int, max_2x: int) -> str:
    if kind == "point":
        return f"Ship loss ({ship_class})"
    return f"Ship loss ({ship_class}, envelope {min_2x}-{max_2x})"


def _gift_label(ship_class: FleetShipClass, player_id: int) -> str:
    return f"Gift {ship_class} to player {player_id}"


def _trade_label(ship_class: FleetShipClass, player_id: int) -> str:
    return f"Trade {ship_class} with player {player_id}"
