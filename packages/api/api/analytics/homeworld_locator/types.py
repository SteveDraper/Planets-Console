"""Persisted and serve-time types for the homeworld locator analytic."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_POSSIBLE,
    HomeworldSingleStarbasePromotion,
    InferredHomeworldCandidate,
    LocationProvenance,
    OriginDistanceObservation,
    SectorOwnerMember,
)


@dataclass(frozen=True)
class HomeworldCandidateRecord:
    """One homeworld candidate (materialized view; not the durable assertion store)."""

    planet_id: int
    perspective: int | None
    confidence_tier: str
    attribution: str = ATTRIBUTION_INFERRED
    """Legacy field retained on the dataclass; durable authority is provenance lists.

    Persist and derive keep this as ``inferred``. Wire emit may map
    ``asserted_cue`` → ``user_asserted`` for FE compat (ADR 0010).
    """

    is_most_probable: bool = False
    asserted_cue: bool = False
    """Derived: asserted-strength provenance present on location and/or ownership."""


@dataclass(frozen=True)
class HomeworldLocatorGameState:
    """Game-global homeworld locator state (candidates + baseline + asserts)."""

    candidates: tuple[HomeworldCandidateRecord, ...]
    baseline_turn: int
    baseline_degraded: bool
    settings_fingerprint: tuple[object, ...] = ()
    baseline_algorithm_version: int = 0
    """``HOMEWORLD_BASELINE_ALGORITHM_VERSION`` at last baseline write; 0 = pre-version."""
    asserted_location_provenances: tuple[LocationProvenance, ...] = ()
    """Durable UI location asserts (positive only); merged above evidence read."""
    asserted_sector_ownership: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...] = ()
    """Durable UI ownership asserts keyed by sector index when sectors exist."""
    asserted_planet_ownership: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...] = ()
    """Durable UI ownership asserts keyed by planet id when sectors do not exist."""


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
    location_provenances: tuple[LocationProvenance, ...] = ()
    """Machine location provenances accumulated through this turn (not UI asserts)."""
    evidence_algorithm_version: int = 0
    """``HOMEWORLD_EVIDENCE_ALGORITHM_VERSION`` at last refine write; 0 = pre-version."""
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


def ensure_candidates_for_asserted_locations(
    *,
    inferred: Sequence[HomeworldCandidateRecord],
    asserted_location_provenances: Sequence[LocationProvenance],
) -> tuple[HomeworldCandidateRecord, ...]:
    """Keep inferred rows; add possible shells for asserted location planets missing from set."""
    by_planet = {row.planet_id: row for row in inferred}
    for provenance in asserted_location_provenances:
        if provenance.planet_id in by_planet:
            continue
        by_planet[provenance.planet_id] = HomeworldCandidateRecord(
            planet_id=provenance.planet_id,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        )
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
    "ensure_candidates_for_asserted_locations",
]
