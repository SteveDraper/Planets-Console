"""Derive candidate confidence / owner / asserted cue from merged provenances (#37)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from api.analytics.homeworld_locator.evidence_strength import (
    LocationAxisResolution,
    provenance_has_asserted_strength,
    resolve_location_axis,
    resolve_ownership_axis,
)
from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    LocationProvenance,
    SectorOwnerMember,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord


def collect_location_provenances_for_planet(
    provenances: Sequence[LocationProvenance],
    *,
    planet_id: int,
) -> tuple[LocationProvenance, ...]:
    return tuple(row for row in provenances if row.planet_id == planet_id)


def _confidence_for_planet(
    *,
    planet_id: int,
    prior_tier: str,
    has_location_provenances: bool,
    location_resolution: LocationAxisResolution,
) -> str:
    """Map one planet onto confidence from a single ``LocationAxisResolution``.

    Non-empty merged location lists are authoritative (ADR 0010): the axis
    winner is definite; every other planet is possible -- ``prior_tier`` must
    not preserve false definites. Empty list falls back to the candidate row
    tier (pre-mint / transitional aggregates).
    """
    if not has_location_provenances:
        return prior_tier
    if location_resolution.is_definite and location_resolution.resolved_planet_id == planet_id:
        return CONFIDENCE_DEFINITE
    return CONFIDENCE_POSSIBLE


def derive_candidates_from_merged_evidence(
    candidates: Sequence[HomeworldCandidateRecord],
    merged: MergedHomeworldEvidence,
    *,
    planet_sector_index: Mapping[int, int] | None = None,
) -> tuple[HomeworldCandidateRecord, ...]:
    """Apply location strength resolution and asserted cues onto candidate rows.

    When ``planet_sector_index`` is provided, ownership cues/bind use sector-keyed
    merged sets. Otherwise planet-keyed asserted ownership is used. Unique
    ownership binds ``perspective`` only when the row is still unbound
    (``perspective is None``) -- both keying modes share that preserve policy.
    """
    has_location_provenances = bool(merged.location_provenances)
    location_resolution = resolve_location_axis(merged.location_provenances)
    definite_ids = (
        frozenset({location_resolution.resolved_planet_id})
        if location_resolution.is_definite and location_resolution.resolved_planet_id is not None
        else frozenset()
    )
    sector_members: dict[int, tuple[SectorOwnerMember, ...]] = dict(merged.sector_owner_sets)
    planet_members: dict[int, tuple[SectorOwnerMember, ...]] = dict(merged.planet_owner_sets)

    derived: list[HomeworldCandidateRecord] = []
    for row in candidates:
        planet_location = collect_location_provenances_for_planet(
            merged.location_provenances,
            planet_id=row.planet_id,
        )
        confidence = _confidence_for_planet(
            planet_id=row.planet_id,
            prior_tier=row.confidence_tier,
            has_location_provenances=has_location_provenances,
            location_resolution=location_resolution,
        )

        ownership_for_cue: tuple[SectorOwnerMember, ...] = ()
        perspective = row.perspective
        if planet_sector_index is not None:
            sector_index = planet_sector_index.get(row.planet_id)
            if sector_index is not None:
                ownership_for_cue = sector_members.get(sector_index, ())
                ownership_resolution = resolve_ownership_axis(
                    ownership_for_cue,
                    location_definite_planet_ids=definite_ids,
                )
                if ownership_resolution.is_unique and perspective is None:
                    perspective = ownership_resolution.resolved_owner_slot
        elif row.planet_id in planet_members:
            ownership_for_cue = planet_members[row.planet_id]
            ownership_resolution = resolve_ownership_axis(
                ownership_for_cue,
                location_definite_planet_ids=definite_ids,
            )
            if ownership_resolution.is_unique and perspective is None:
                perspective = ownership_resolution.resolved_owner_slot

        asserted_cue = provenance_has_asserted_strength(
            location_provenances=planet_location,
            ownership_members=ownership_for_cue,
        )
        derived.append(
            replace(
                row,
                confidence_tier=confidence,
                perspective=perspective,
                asserted_cue=asserted_cue,
            )
        )
    return tuple(derived)


__all__ = [
    "collect_location_provenances_for_planet",
    "derive_candidates_from_merged_evidence",
]
