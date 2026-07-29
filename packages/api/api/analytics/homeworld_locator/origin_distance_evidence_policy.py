"""Soft origin-distance evidence freeze at shared ship limit."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from api.analytics.homeworld_locator.models import OriginDistanceObservation
from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.concepts.ship_limit import is_at_or_over_shared_ship_limit
from api.errors import ValidationError
from api.models.game import TurnInfo


def observations_through_turn(
    observations: Sequence[OriginDistanceObservation],
    through: int | None,
) -> tuple[OriginDistanceObservation, ...]:
    """Keep observations at or before ``through``; pass all when ``through`` is unset."""
    if through is None:
        return tuple(observations)
    return tuple(observation for observation in observations if observation.turn <= through)


def effective_origin_distance_observations(
    aggregate: HomeworldEvidenceAggregate,
) -> tuple[OriginDistanceObservation, ...]:
    """Observations that participate in layout-prior soft evidence cost."""
    return observations_through_turn(
        aggregate.origin_distance_observations,
        aggregate.origin_distance_evidence_through_turn,
    )


def earliest_shared_ship_limit_turn(history: Sequence[TurnInfo]) -> int | None:
    """Earliest turn number in ``history`` at/over the shared ship limit."""
    earliest: int | None = None
    for sample in history:
        if not is_at_or_over_shared_ship_limit(sample.settings, sample.scores):
            continue
        turn_number = sample.settings.turn
        if earliest is None or turn_number < earliest:
            earliest = turn_number
    return earliest


def load_scoreboard_history_for_ship_limit_freeze(
    *,
    shell_turn: TurnInfo,
    load_turn: Callable[[int], TurnInfo | None],
) -> tuple[TurnInfo, ...]:
    """Load contiguous scoreboard turns from the ensure floor through shell.

    Incomplete history is a hard failure: guessing a cutoff from a partial chain
    would leave post-limit observations sticky forever. Matches the evidence-chain
    convention that turns on ``[ensure_floor, shell]`` must be loadable.
    """
    shell = shell_turn.settings.turn
    floor = accelerated_ensure_floor(shell_turn.settings, shell)
    history: list[TurnInfo] = []
    for turn_number in range(floor, shell):
        loaded = load_turn(turn_number)
        if loaded is None:
            raise ValidationError(
                f"scoreboard history turn {turn_number} is required to resolve "
                "origin-distance evidence freeze at ship limit "
                "(sign in to auto-fetch missing turns for the evidence chain)"
            )
        history.append(loaded)
    history.append(shell_turn)
    return tuple(history)


def resolve_origin_distance_evidence_through_turn(
    prior: HomeworldEvidenceAggregate,
    *,
    turn: TurnInfo,
    scoreboard_history: Sequence[TurnInfo] | None = None,
) -> int | None:
    """Sticky soft-evidence cutoff from earliest shared ship-limit crossing.

    Returns the last turn whose origin-distance observations may still contribute.
    Once set on ``prior``, the cutoff never advances or clears.

    On first freeze (current shell at/over shared ship limit), the cutoff is
    ``T_limit - 1`` where ``T_limit`` is the earliest turn in ``scoreboard_history``
    at/over the limit. When ``scoreboard_history`` is omitted, only ``turn`` is
    consulted (shell-only; for unit tests). Production ensure supplies contiguous
    history from the accelerated ensure floor through the shell.
    """
    if prior.origin_distance_evidence_through_turn is not None:
        return prior.origin_distance_evidence_through_turn
    if not is_at_or_over_shared_ship_limit(turn.settings, turn.scores):
        return None
    history = scoreboard_history if scoreboard_history is not None else (turn,)
    t_limit = earliest_shared_ship_limit_turn(history)
    if t_limit is None:
        # Shell is over-limit; treat shell as the crossing when history omitted it.
        t_limit = turn.settings.turn
    return max(0, t_limit - 1)
