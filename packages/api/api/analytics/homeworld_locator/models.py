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


# --- Ownership evidence (#269) ---

PROVENANCE_SHIP_TRAVEL_ENVELOPE = "ship_travel_envelope"
PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP = "preferred_candidate_ownership"
PROVENANCE_NEARBY_PLANET_OWNERSHIP = "nearby_planet_ownership"

AGE_SOURCE_FLEET_BUILT_TURN = "fleet_built_turn"
AGE_SOURCE_SHIP_ID_SCOREBOARD = "ship_id_scoreboard"


@dataclass(frozen=True)
class OwnershipProvenance:
    """One machine-fact reason a slot is in a sector's possible-owner set."""

    kind: str
    turn: int
    ship_id: int | None = None
    planet_id: int | None = None
    radius_ly: float | None = None
    distance_ly: float | None = None
    age_source: str | None = None


@dataclass(frozen=True)
class SectorOwnerMember:
    """One possible homeworld owner for a sector, with provenance collection."""

    owner_slot: int
    provenances: tuple[OwnershipProvenance, ...]
