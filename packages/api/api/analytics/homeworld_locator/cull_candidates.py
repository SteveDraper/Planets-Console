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

__all__ = [
    "CullableCandidate",
    "TCullable",
]
