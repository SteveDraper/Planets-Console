"""Persisted and serve-time types for the homeworld locator analytic."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
from api.analytics.homeworld_locator.models import (
    HomeworldSingleStarbasePromotion,
    InferredHomeworldCandidate,
    OriginDistanceObservation,
    SectorOwnerMember,
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
    baseline_algorithm_version: int = 0
    """``HOMEWORLD_BASELINE_ALGORITHM_VERSION`` at last baseline write; 0 = pre-version."""


@dataclass(frozen=True)
class HomeworldEvidenceAggregate:
    """Turn-scoped durable evidence aggregate refined through the shell turn."""

    turn: int
    baseline_turn: int
    """Turn that supplied the homeworld inference baseline for this chain."""

    origin_distance_observations: tuple[OriginDistanceObservation, ...] = ()
    single_starbase_promotions: tuple[HomeworldSingleStarbasePromotion, ...] = ()
    # Sticky soft OD freeze: last turn whose observations participate in layout-prior
    # cost. Set on first shell at/over shared ship limit to T_limit-1, where T_limit
    # is the earliest scoreboard-history turn at/over the limit.
    origin_distance_evidence_through_turn: int | None = None
    # Ownership evidence (#269): per-sector possible-owner sets + sticky per-owner
    # remaining possible-sector sets (None-equivalent omitted = uninitialized).
    sector_owner_sets: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...] = ()
    """``(sector_index, members)`` rows; empty when no ownership attributions yet."""
    owner_possible_sectors: tuple[tuple[int, tuple[int, ...]], ...] = ()
    """``(owner_slot, remaining_sector_indexes)`` after envelope intersections."""
    # Shell-turn layout-prior selection only; absent until first candidate-view materialize.
    layout_prior_algorithm_version: int | None = None
    layout_prior_input_fingerprint: tuple[tuple[int, str, int | None], ...] = ()
    """Post-promote/cull candidate triples that fed selection (planet, tier, perspective)."""
    layout_prior_evidence_lambda: float | None = None
    """Configured soft-evidence λ used for the stored selection; part of the reuse key."""
    layout_prior_evidence_fingerprint: str | None = None
    """SHA-256 hex of effective soft OD observations; part of the reuse key."""
    most_probable_planet_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class HomeworldCandidateView:
    """Shell candidate view for map/table (selection may be reused from shell aggregate)."""

    candidates: tuple[HomeworldCandidateRecord, ...]
    baseline_turn: int
    baseline_degraded: bool
    available: bool
    inactive_reason: str | None = None
    # Soft layout-prior evidence from the shell evidence aggregate (may be empty).
    origin_distance_observations: tuple[OriginDistanceObservation, ...] = ()


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
