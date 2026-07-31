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


def first_shared_ship_limit_turn(
    *,
    shell_turn: TurnInfo,
    load_turn: Callable[[int], TurnInfo | None],
) -> int:
    """Earliest turn at/over the shared ship limit on ``[ensure_floor, shell]``.

    ``shell_turn`` must itself be at/over the limit, so a crossing always exists;
    the shell is the answer when no earlier turn had crossed.

    Scoreboard turns before the crossing must be loadable: guessing a cutoff from
    a partial chain would leave post-limit observations sticky forever. Matches the
    evidence-chain convention that turns on ``[ensure_floor, shell]`` are required.
    """
    shell = shell_turn.settings.turn
    floor = accelerated_ensure_floor(shell_turn.settings, shell)
    for turn_number in range(floor, shell):
        loaded = load_turn(turn_number)
        if loaded is None:
            raise ValidationError(
                f"scoreboard history turn {turn_number} is required to resolve "
                "origin-distance evidence freeze at ship limit "
                "(sign in to auto-fetch missing turns for the evidence chain)"
            )
        if is_at_or_over_shared_ship_limit(loaded.settings, loaded.scores):
            return turn_number
    return shell


def resolve_origin_distance_evidence_through_turn(
    prior: HomeworldEvidenceAggregate,
    *,
    turn: TurnInfo,
    load_turn: Callable[[int], TurnInfo | None],
) -> int | None:
    """Sticky soft-evidence cutoff from earliest shared ship-limit crossing.

    Returns the last turn whose origin-distance observations may still contribute.
    Once set on ``prior``, the cutoff never advances or clears.

    On first freeze (current shell at/over shared ship limit), the cutoff is
    ``T_limit - 1`` for the earliest scoreboard turn at/over the limit, found by
    walking ``[ensure_floor, shell]`` through ``load_turn``. Scoreboard turns are
    only loaded when a freeze is actually being decided.
    """
    if prior.origin_distance_evidence_through_turn is not None:
        return prior.origin_distance_evidence_through_turn
    if not is_at_or_over_shared_ship_limit(turn.settings, turn.scores):
        return None
    crossing = first_shared_ship_limit_turn(shell_turn=turn, load_turn=load_turn)
    return max(0, crossing - 1)
