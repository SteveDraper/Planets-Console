"""HTTP body for the league team directory read."""

from __future__ import annotations

from pydantic import BaseModel


class LeagueTeamName(BaseModel):
    """One league team id and its Planets.nu group name, when resolved."""

    id: int
    name: str | None


class LeagueTeamsResponse(BaseModel):
    """Distinct league teams on a game's stored players. ``name`` is null when unresolved."""

    teams: list[LeagueTeamName]
