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

    Prefer durable asserted location planet ids. ``asserted_cue`` / legacy
    ``user_asserted`` attribution remain for callers that already stamped those
    views (or unit tests that exercise the legacy path directly).
    """
    from api.analytics.homeworld_locator.constants import ATTRIBUTION_USER_ASSERTED

    if row.planet_id in protected_planet_ids:
        return True
    asserted_cue = getattr(row, "asserted_cue", False)
    return bool(asserted_cue) or row.attribution == ATTRIBUTION_USER_ASSERTED


__all__ = [
    "CullableCandidate",
    "TCullable",
    "candidate_is_assert_protected",
]
