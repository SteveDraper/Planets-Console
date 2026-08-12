"""Derive candidate confidence / owner / asserted cue from merged provenances (#37)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace

from api.analytics.homeworld_locator.evidence_strength import (
    LocationAxisResolution,
    location_has_asserted_strength,
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

# Sentinel sector key for planets (and their location provenances) outside the
# annular sector index, or for the single global bucket when no sector map exists.
_UNASSIGNED_SECTOR: int | None = None


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
    bucket_has_location_provenances: bool,
    location_resolution: LocationAxisResolution,
) -> str:
    """Map one planet onto confidence from its location-axis bucket resolution.

    Non-empty bucket lists are authoritative (ADR 0010): the axis winner is
    definite; every other planet in that bucket is possible -- ``prior_tier``
    must not preserve false definites. Empty bucket falls back to the candidate
    row tier (pre-mint / transitional aggregates / other sectors' evidence).
    """
    if not bucket_has_location_provenances:
        return prior_tier
    if location_resolution.is_definite and location_resolution.resolved_planet_id == planet_id:
        return CONFIDENCE_DEFINITE
    return CONFIDENCE_POSSIBLE


def _location_buckets(
    provenances: Sequence[LocationProvenance],
    planet_sector_index: Mapping[int, int] | None,
) -> dict[int | None, list[LocationProvenance]]:
    """Group location provenances by homeworld sector (or one global bucket)."""
    if planet_sector_index is None:
        return {_UNASSIGNED_SECTOR: list(provenances)}

    buckets: dict[int | None, list[LocationProvenance]] = defaultdict(list)
    for row in provenances:
        buckets[planet_sector_index.get(row.planet_id)].append(row)
    return dict(buckets)


def _bucket_key_for_planet(
    planet_id: int,
    planet_sector_index: Mapping[int, int] | None,
) -> int | None:
    if planet_sector_index is None:
        return _UNASSIGNED_SECTOR
    return planet_sector_index.get(planet_id)


def derive_candidates_from_merged_evidence(
    candidates: Sequence[HomeworldCandidateRecord],
    merged: MergedHomeworldEvidence,
    *,
    race_id_by_owner_slot: Mapping[int, int],
    planet_sector_index: Mapping[int, int] | None = None,
) -> tuple[HomeworldCandidateRecord, ...]:
    """Apply location strength resolution and asserted cues onto candidate rows.

    Location max-strength resolution is **per homeworld sector** when
    ``planet_sector_index`` is provided (one definite location per sector ≈ per
    player). Same-strength conflicts only within a sector stay ambiguous.
    Without a sector index (non-circular / no partition), resolve stays global.

    When ``planet_sector_index`` is provided, ownership cues use sector-keyed
    merged sets. Unique sector owners bind ``perspective`` via overlay
    projection in ``apply_unique_owner_orphan_bind`` -- not here -- so
    cross-sector settled trim is the same test as overlay ``is_pinned``.
    Without a sector index, planet-keyed asserted ownership may bind
    ``perspective`` when unique and the row is still unbound.
    ``race_id_by_owner_slot`` is required (empty map allowed when no race context).
    """
    location_buckets = _location_buckets(merged.location_provenances, planet_sector_index)
    location_resolutions = {
        key: resolve_location_axis(rows) for key, rows in location_buckets.items()
    }
    empty_resolution = resolve_location_axis(())
    definite_ids = frozenset(
        resolution.resolved_planet_id
        for resolution in location_resolutions.values()
        if resolution.is_definite and resolution.resolved_planet_id is not None
    )
    sector_members: dict[int, tuple[SectorOwnerMember, ...]] = dict(merged.sector_owner_sets)
    planet_members: dict[int, tuple[SectorOwnerMember, ...]] = dict(merged.planet_owner_sets)

    derived: list[HomeworldCandidateRecord] = []
    for row in candidates:
        planet_location = collect_location_provenances_for_planet(
            merged.location_provenances,
            planet_id=row.planet_id,
        )
        bucket_key = _bucket_key_for_planet(row.planet_id, planet_sector_index)
        bucket_rows = location_buckets.get(bucket_key, [])
        location_resolution = location_resolutions.get(bucket_key, empty_resolution)
        confidence = _confidence_for_planet(
            planet_id=row.planet_id,
            prior_tier=row.confidence_tier,
            bucket_has_location_provenances=bool(bucket_rows),
            location_resolution=location_resolution,
        )

        ownership_for_cue: tuple[SectorOwnerMember, ...] = ()
        perspective = row.perspective
        if planet_sector_index is not None:
            sector_index = planet_sector_index.get(row.planet_id)
            if sector_index is not None:
                ownership_for_cue = sector_members.get(sector_index, ())
        elif row.planet_id in planet_members:
            ownership_for_cue = planet_members[row.planet_id]
            ownership_resolution = resolve_ownership_axis(
                ownership_for_cue,
                race_id_by_owner_slot=race_id_by_owner_slot,
                location_definite_planet_ids=definite_ids,
            )
            if ownership_resolution.is_unique and perspective is None:
                perspective = ownership_resolution.resolved_owner_slot

        location_asserted = location_has_asserted_strength(planet_location)
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
                location_asserted=location_asserted,
            )
        )
    return tuple(derived)


__all__ = [
    "collect_location_provenances_for_planet",
    "derive_candidates_from_merged_evidence",
]
