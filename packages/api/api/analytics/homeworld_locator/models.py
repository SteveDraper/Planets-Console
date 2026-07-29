"""Pure-domain result types for homeworld locator baseline inference."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED

CONFIDENCE_DEFINITE = "definite"
CONFIDENCE_POSSIBLE = "possible"


@dataclass(frozen=True)
class ClusterNeighborCounts:
    """Neighbor planet counts in map-gen homeworld neighborhood bands."""

    very_close: int
    """Planets other than the candidate within 81 LY."""

    close_band: int
    """Planets other than the candidate in the 81--162 LY band."""


@dataclass(frozen=True)
class InferredHomeworldCandidate:
    """One baseline-inferred homeworld candidate (slot-anchored or orphan)."""

    planet_id: int
    perspective: int | None
    """Player slot when slot-anchored; ``None`` for orphan homeworld candidates."""

    confidence_tier: str
    """``definite`` or ``possible``."""

    attribution: str = ATTRIBUTION_INFERRED
    """``inferred`` for baseline-emitted candidates."""


EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD = "single_starbase_new_build"


@dataclass(frozen=True)
class OriginDistanceObservation:
    """One location-deduped origin-distance observation with match set M.

    Keyed by (turn, x, y): co-located ships on the same turn merge by unioning M.
    ``matched_planet_ids`` is the sorted candidate planet ids in the origin-distance band.
    """

    turn: int
    x: int
    y: int
    matched_planet_ids: tuple[int, ...]


@dataclass(frozen=True)
class HomeworldSingleStarbasePromotion:
    """Immediate possible->definite promotion from the single-starbase new-build rule."""

    planet_id: int
    turn: int
    kind: str = EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD
