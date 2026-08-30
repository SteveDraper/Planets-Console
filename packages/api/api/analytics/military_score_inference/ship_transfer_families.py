"""Catalog actions for ship loss, gift, trade, and acquired ship.

Departures are prior-fleet decrease candidates, not inverted ship-build combos.
Families are ranked ``solutions[]`` actions with counterparty player id when
pairing pins a row. Admitted from the first ship-bearing cheap step (not via
tier aggregate allowlist).
"""

from __future__ import annotations

from collections import defaultdict

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


def is_ship_transfer_action_id(action_id: str) -> bool:
    return action_id.startswith(
        (
            SHIP_LOSS_ACTION_PREFIX,
            GIFT_ACTION_PREFIX,
            TRADE_ACTION_PREFIX,
            ACQUIRED_SHIP_ACTION_PREFIX,
        )
    )


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


def build_ship_transfer_actions(
    observation: InferenceObservation,
    *,
    peer_rows: tuple[PublicScoreboardRow, ...],
    prior_fleet_records: tuple[FleetShipRecord, ...],
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
) -> tuple[CandidateAction, ...]:
    """Admit loss / gift / trade / acquired actions for this scoreboard row."""
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
        buildable_hull_ids=buildable_hull_ids,
    )
    actions: list[CandidateAction] = []
    actions.extend(_loss_actions(observation, pairing, candidates))
    actions.extend(_gift_actions(pairing, candidates))
    actions.extend(_trade_actions(pairing, candidates, observation))
    actions.extend(_acquired_actions(pairing))
    return tuple(action for action in actions if action.upper_bound > 0)


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
            point, score_min, score_max = _departure_score_bounds(kind, min_2x, max_2x)
            upper = len(group) if class_upper is None else min(class_upper, len(group))
            if upper <= 0:
                continue
            action_id = _loss_action_id(ship_class, kind, min_2x, max_2x)
            actions.append(
                CandidateAction(
                    id=action_id,
                    label=_loss_label(ship_class, kind, min_2x, max_2x),
                    score_delta_2x=point,
                    warship_delta=-1 if ship_class == "warship" else 0,
                    freighter_delta=-1 if ship_class == "freighter" else 0,
                    score_delta_2x_min=score_min if kind == "envelope" else None,
                    score_delta_2x_max=score_max if kind == "envelope" else None,
                    prior_warship_usage=1 if ship_class == "warship" else 0,
                    prior_freighter_usage=1 if ship_class == "freighter" else 0,
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
                point, score_min, score_max = _departure_score_bounds(kind, min_2x, max_2x)
                upper = min(needed, len(group))
                actions.append(
                    CandidateAction(
                        id=_gift_action_id(
                            ship_class, match.counterparty_player_id, kind, min_2x, max_2x
                        ),
                        label=_gift_label(ship_class, match.counterparty_player_id),
                        score_delta_2x=point,
                        warship_delta=-1 if ship_class == "warship" else 0,
                        freighter_delta=-1 if ship_class == "freighter" else 0,
                        score_delta_2x_min=score_min if kind == "envelope" else None,
                        score_delta_2x_max=score_max if kind == "envelope" else None,
                        counterparty_player_id=match.counterparty_player_id,
                        prior_warship_usage=1 if ship_class == "warship" else 0,
                        prior_freighter_usage=1 if ship_class == "freighter" else 0,
                        upper_bound=upper,
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
        outgoing_class: FleetShipClass | None = None
        if match.warship_delta < 0:
            outgoing_class = "warship"
        elif match.freighter_delta < 0:
            outgoing_class = "freighter"
        elif match.warship_delta == 0 and match.freighter_delta == 0:
            outgoing_class = "warship"
        if outgoing_class is None:
            continue
        grouped = _group_candidates(candidates, outgoing_class)
        if not grouped:
            continue
        for (kind, min_2x, max_2x), group in grouped.items():
            if match.warship_delta == 0 and match.freighter_delta == 0:
                point = observation.military_delta_2x
                score_min = point
                score_max = point
                envelope = False
            else:
                point, score_min, score_max = _departure_score_bounds(kind, min_2x, max_2x)
                envelope = kind == "envelope"
            if not group:
                continue
            actions.append(
                CandidateAction(
                    id=f"{TRADE_ACTION_PREFIX}with:{match.counterparty_player_id}",
                    label=f"Trade with player {match.counterparty_player_id}",
                    score_delta_2x=point,
                    warship_delta=match.warship_delta,
                    freighter_delta=match.freighter_delta,
                    score_delta_2x_min=score_min if envelope else None,
                    score_delta_2x_max=score_max if envelope else None,
                    counterparty_player_id=match.counterparty_player_id,
                    prior_warship_usage=1 if outgoing_class == "warship" else 0,
                    prior_freighter_usage=1 if outgoing_class == "freighter" else 0,
                    upper_bound=1,
                )
            )
            break
    return actions


def _acquired_actions(pairing: PublicScoreboardPairing) -> list[CandidateAction]:
    actions: list[CandidateAction] = []
    for match in pairing.matches:
        if match.family != "acquired":
            continue
        incoming_military = -match.counterparty_military_delta_2x
        if match.warship_delta > 0:
            actions.append(
                CandidateAction(
                    id=f"{ACQUIRED_SHIP_ACTION_PREFIX}warship:from:{match.counterparty_player_id}",
                    label=f"Acquired warship from player {match.counterparty_player_id}",
                    score_delta_2x=incoming_military,
                    warship_delta=1,
                    counterparty_player_id=match.counterparty_player_id,
                    upper_bound=match.warship_delta,
                )
            )
        if match.freighter_delta > 0:
            freighter_military = 0 if match.warship_delta > 0 else incoming_military
            actions.append(
                CandidateAction(
                    id=f"{ACQUIRED_SHIP_ACTION_PREFIX}freighter:from:{match.counterparty_player_id}",
                    label=f"Acquired freighter from player {match.counterparty_player_id}",
                    score_delta_2x=freighter_military,
                    freighter_delta=1,
                    counterparty_player_id=match.counterparty_player_id,
                    upper_bound=match.freighter_delta,
                )
            )
    return actions


def _loss_action_id(ship_class: FleetShipClass, kind: str, min_2x: int, max_2x: int) -> str:
    if kind == "point":
        return f"{SHIP_LOSS_ACTION_PREFIX}{ship_class}:point:{min_2x}"
    return f"{SHIP_LOSS_ACTION_PREFIX}{ship_class}:envelope:{min_2x}:{max_2x}"


def _gift_action_id(
    ship_class: FleetShipClass,
    player_id: int,
    kind: str,
    min_2x: int,
    max_2x: int,
) -> str:
    if kind == "point":
        return f"{GIFT_ACTION_PREFIX}{ship_class}:to:{player_id}:point:{min_2x}"
    return f"{GIFT_ACTION_PREFIX}{ship_class}:to:{player_id}:envelope:{min_2x}:{max_2x}"


def _loss_label(ship_class: FleetShipClass, kind: str, min_2x: int, max_2x: int) -> str:
    if kind == "point":
        return f"Ship loss ({ship_class})"
    return f"Ship loss ({ship_class}, envelope {min_2x}-{max_2x})"


def _gift_label(ship_class: FleetShipClass, player_id: int) -> str:
    return f"Gift {ship_class} to player {player_id}"
