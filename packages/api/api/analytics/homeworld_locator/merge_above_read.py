"""Merge game-global asserted provenances with turn-scoped machine evidence.

This is the sole encapsulator of the storage split (ADR 0010): callers receive
one location list and one ownership map per sector and do not know which facts
came from game-global vs the evidence aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.homeworld_locator.models import LocationProvenance, SectorOwnerMember
from api.analytics.homeworld_locator.ownership_evidence import add_provenance_to_sector_owner_set
from api.analytics.homeworld_locator.types import (
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
)


@dataclass(frozen=True)
class MergedHomeworldEvidence:
    """Unified provenance view after merge-above-read."""

    location_provenances: tuple[LocationProvenance, ...]
    sector_owner_sets: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...]
    """Merged sector-keyed ownership (machine ∪ asserted sector ownership)."""
    planet_owner_sets: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...]
    """Asserted planet-keyed ownership when sectors do not exist (machine has none)."""


def _merge_owner_set_maps(
    machine: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...],
    asserted: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...],
) -> tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...]:
    by_key = dict(machine)
    for key, asserted_members in asserted:
        prior = by_key.get(key, ())
        merged = prior
        for member in asserted_members:
            for provenance in member.provenances:
                merged = add_provenance_to_sector_owner_set(
                    merged,
                    owner_slot=member.owner_slot,
                    provenance=provenance,
                )
        by_key[key] = merged
    return tuple(sorted(by_key.items(), key=lambda item: item[0]))


def merge_homeworld_evidence_above_read(
    *,
    game_state: HomeworldLocatorGameState,
    aggregate: HomeworldEvidenceAggregate | None,
) -> MergedHomeworldEvidence:
    """Union game-global asserts with machine provenances from the shell aggregate."""
    machine_location = aggregate.location_provenances if aggregate is not None else ()
    location = (*machine_location, *game_state.asserted_location_provenances)
    machine_sectors = aggregate.sector_owner_sets if aggregate is not None else ()
    sector_owner_sets = _merge_owner_set_maps(
        machine_sectors,
        game_state.asserted_sector_ownership,
    )
    return MergedHomeworldEvidence(
        location_provenances=location,
        sector_owner_sets=sector_owner_sets,
        planet_owner_sets=game_state.asserted_planet_ownership,
    )


__all__ = [
    "MergedHomeworldEvidence",
    "merge_homeworld_evidence_above_read",
]
