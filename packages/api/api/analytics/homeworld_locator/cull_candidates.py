"""Shared structural types for homeworld candidate cull helpers."""

from __future__ import annotations

from collections.abc import Set
from typing import Protocol, TypeVar


class CullableCandidate(Protocol):
    """Candidate shape required by co-sector and neighborhood culls."""

    @property
    def planet_id(self) -> int: ...

    @property
    def confidence_tier(self) -> str: ...

    @property
    def location_asserted(self) -> bool: ...

    @property
    def perspective(self) -> int | None: ...


TCullable = TypeVar("TCullable", bound=CullableCandidate)


def candidate_is_assert_protected(
    row: CullableCandidate,
    *,
    protected_planet_ids: Set[int] = frozenset(),
) -> bool:
    """True when culls must keep this row.

    Prefer durable asserted location planet ids. ``location_asserted`` covers
    already-derived candidate views. Ownership-only ``asserted_cue`` does not
    protect: a sector ownership assert lights that cue on every candidate in
    the sector, which would otherwise block co-sector cull after a location pin.
    ``attribution`` is not authority (ADR 0010).
    """
    if row.planet_id in protected_planet_ids:
        return True
    return row.location_asserted


__all__ = [
    "CullableCandidate",
    "TCullable",
    "candidate_is_assert_protected",
]
