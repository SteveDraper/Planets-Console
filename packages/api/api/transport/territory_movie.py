"""HTTP body for one packed Territory movie."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TerritoryMovieRectangle(BaseModel):
    """Map rectangle the ring grid is measured from, centered on (2000, 2000)."""

    left: float
    bottom: float
    width: float
    height: float


class TerritoryMovieLegendEntry(BaseModel):
    """One owner who holds a planet on any turn in the span. Name is null when unknown."""

    id: int
    name: str | None


class TerritoryMovieResponse(BaseModel):
    """Rings, planet dots, and the span-wide legend for one perspective.

    rings and planets are base64 of gzip-compressed little-endian uint16 bytes.
    The page inflates them. Colors, selection, and HTML are not in this body.
    """

    turn: int = Field(description="GameInfo.game.turn. Frames are host turns 1 through this turn.")
    rectangle: TerritoryMovieRectangle
    rings: str = Field(
        description=(
            "Base64 gzip of the four sections, in order: team-territory, "
            "player-territory, team-territory-owned-only, player-territory-owned-only. "
            "Each section is turns 1..turn. A turn is a component count, then that many "
            "components of group id, vertex count, and dx, dy pairs on a 0.1 LY grid."
        )
    )
    planets: str = Field(
        description=(
            "Base64 gzip of a uint16 count, then rows sorted by planet id: "
            "id, host x, host y, first_turn."
        )
    )
    players: list[TerritoryMovieLegendEntry]
    teams: list[TerritoryMovieLegendEntry]
