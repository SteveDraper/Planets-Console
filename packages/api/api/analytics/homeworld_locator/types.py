"""Persisted and serve-time types for the homeworld locator analytic."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
from api.analytics.homeworld_locator.models import (
    HomeworldIndependentEvidenceHit,
    HomeworldSingleStarbasePromotion,
    InferredHomeworldCandidate,
)


@dataclass(frozen=True)
class HomeworldCandidateRecord:
    """One durable or served homeworld candidate (inferred or user-asserted)."""

    planet_id: int
    perspective: int | None
    confidence_tier: str
    attribution: str = ATTRIBUTION_INFERRED
    is_most_probable: bool = False


@dataclass(frozen=True)
class HomeworldLocatorGameState:
    """Game-global homeworld locator state (candidates + baseline metadata)."""

    candidates: tuple[HomeworldCandidateRecord, ...]
    baseline_turn: int
    baseline_degraded: bool
    settings_fingerprint: tuple[object, ...] = ()


@dataclass(frozen=True)
class HomeworldEvidenceAggregate:
    """Turn-scoped durable evidence aggregate refined through the shell turn."""

    turn: int
    baseline_turn: int
    """Turn that supplied the homeworld inference baseline for this chain."""

    evidence_hits: tuple[HomeworldIndependentEvidenceHit, ...] = ()
    single_starbase_promotions: tuple[HomeworldSingleStarbasePromotion, ...] = ()
    # Shell-turn layout-prior selection only; absent until first candidate-view materialize.
    layout_prior_algorithm_version: int | None = None
    layout_prior_promotion_threshold: int | None = None
    layout_prior_input_fingerprint: tuple[tuple[int, str, int | None], ...] = ()
    most_probable_planet_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class HomeworldCandidateView:
    """Shell candidate view for map/table (selection may be reused from shell aggregate)."""

    candidates: tuple[HomeworldCandidateRecord, ...]
    baseline_turn: int
    baseline_degraded: bool
    available: bool
    inactive_reason: str | None = None


@dataclass(frozen=True)
class HomeworldBaselineEnsureResult:
    """Outcome of baseline-only ensure (game-global + floor aggregate)."""

    game_state: HomeworldLocatorGameState
    floor_aggregate: HomeworldEvidenceAggregate
    recomputed: bool


def candidate_records_from_inferred(
    inferred: tuple[InferredHomeworldCandidate, ...],
) -> tuple[HomeworldCandidateRecord, ...]:
    return tuple(
        HomeworldCandidateRecord(
            planet_id=row.planet_id,
            perspective=row.perspective,
            confidence_tier=row.confidence_tier,
            attribution=row.attribution,
        )
        for row in inferred
    )


def merge_candidates_preserving_user_asserted(
    *,
    inferred: tuple[HomeworldCandidateRecord, ...],
    existing: tuple[HomeworldCandidateRecord, ...] | None,
) -> tuple[HomeworldCandidateRecord, ...]:
    """Replace inferred rows; keep user-asserted records from *existing* (#37)."""
    from api.analytics.homeworld_locator.constants import ATTRIBUTION_USER_ASSERTED

    preserved: list[HomeworldCandidateRecord] = []
    if existing is not None:
        preserved = [row for row in existing if row.attribution == ATTRIBUTION_USER_ASSERTED]
    by_planet = {row.planet_id: row for row in inferred}
    for row in preserved:
        by_planet[row.planet_id] = row
    return tuple(sorted(by_planet.values(), key=lambda row: row.planet_id))


def empty_candidate_view(*, inactive_reason: str | None = None) -> HomeworldCandidateView:
    return HomeworldCandidateView(
        candidates=(),
        baseline_turn=0,
        baseline_degraded=False,
        available=inactive_reason is None,
        inactive_reason=inactive_reason,
    )


__all__ = [
    "HomeworldBaselineEnsureResult",
    "HomeworldCandidateRecord",
    "HomeworldCandidateView",
    "HomeworldEvidenceAggregate",
    "HomeworldLocatorGameState",
    "candidate_records_from_inferred",
    "empty_candidate_view",
    "merge_candidates_preserving_user_asserted",
]
