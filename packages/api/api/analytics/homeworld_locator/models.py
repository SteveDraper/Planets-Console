"""Pure-domain result types for homeworld locator baseline inference."""

from __future__ import annotations

from dataclasses import dataclass

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
