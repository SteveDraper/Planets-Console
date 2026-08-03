"""Shared structural types for homeworld candidate cull helpers."""

from __future__ import annotations

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


def candidate_is_assert_protected(row: CullableCandidate) -> bool:
    """True when culls must keep this row (asserted cue or legacy attribution)."""
    from api.analytics.homeworld_locator.constants import ATTRIBUTION_USER_ASSERTED

    asserted_cue = getattr(row, "asserted_cue", False)
    return bool(asserted_cue) or row.attribution == ATTRIBUTION_USER_ASSERTED


__all__ = [
    "CullableCandidate",
    "TCullable",
    "candidate_is_assert_protected",
]
