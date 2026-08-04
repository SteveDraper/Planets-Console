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
    def attribution(self) -> str: ...

    @property
    def perspective(self) -> int | None: ...


TCullable = TypeVar("TCullable", bound=CullableCandidate)


def candidate_is_assert_protected(
    row: CullableCandidate,
    *,
    protected_planet_ids: Set[int] = frozenset(),
) -> bool:
    """True when culls must keep this row.

    Prefer durable asserted location planet ids. ``asserted_cue`` covers
    already-derived candidate views; ``attribution`` is not authority (ADR 0010).
    """
    if row.planet_id in protected_planet_ids:
        return True
    return bool(getattr(row, "asserted_cue", False))


__all__ = [
    "CullableCandidate",
    "TCullable",
    "candidate_is_assert_protected",
]
