"""BFF transport model for a hosted Territory movie page."""

from __future__ import annotations

from pydantic import BaseModel


class TerritoryMoviePageCreateResponse(BaseModel):
    """Address of one movie document held until its window closes."""

    id: str
    path: str
