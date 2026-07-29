"""Soft origin-distance evidence freeze at shared ship limit."""

from __future__ import annotations

from api.analytics.homeworld_locator.models import OriginDistanceObservation
from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate
from api.concepts.ship_limit import is_at_or_over_shared_ship_limit
from api.models.game import TurnInfo


def effective_origin_distance_observations(
    aggregate: HomeworldEvidenceAggregate,
) -> tuple[OriginDistanceObservation, ...]:
    """Observations that participate in layout-prior soft evidence cost."""
    through = aggregate.origin_distance_evidence_through_turn
    observations = aggregate.origin_distance_observations
    if through is None:
        return observations
    return tuple(observation for observation in observations if observation.turn <= through)


def resolve_origin_distance_evidence_through_turn(
    prior: HomeworldEvidenceAggregate,
    *,
    turn: TurnInfo,
) -> int | None:
    """Sticky soft-evidence cutoff: first turn at/over shared ship limit freezes.

    Returns the last turn whose origin-distance observations may still contribute
    (``turn_number - 1`` when the limit is first observed). Once set on ``prior``,
    the cutoff never advances or clears.
    """
    if prior.origin_distance_evidence_through_turn is not None:
        return prior.origin_distance_evidence_through_turn
    if not is_at_or_over_shared_ship_limit(turn.settings, turn.scores):
        return None
    return max(0, turn.settings.turn - 1)
