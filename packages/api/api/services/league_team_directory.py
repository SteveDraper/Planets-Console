"""Resolve league team ids to Planets.nu group names.

The directory is keyed by league team id, not by game. Stored GameInfo players
supply the ids and a member username to probe. This module is not part of the
team-information analytic.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from api.errors import NotFoundError, UpstreamPlanetsError
from api.models.player import Player
from api.services.game_service import GameService
from api.storage.base import StorageBackend
from api.transport.league_teams import LeagueTeamName, LeagueTeamsResponse

logger = logging.getLogger(__name__)


def league_team_store_key(league_team_id: int) -> str:
    """Durable cache document for one league team id."""
    return f"league-teams/{league_team_id}"


def league_team_name_from_profile(profile: dict[str, Any], league_team_id: int) -> str | None:
    """Return ``_group.name`` for the ``playergroups`` row whose ``groupid`` equals the id."""
    groups = profile.get("playergroups")
    if not isinstance(groups, list):
        return None
    for row in groups:
        if not isinstance(row, dict) or not _same_group_id(row.get("groupid"), league_team_id):
            continue
        group = row.get("_group")
        if not isinstance(group, dict):
            continue
        name = group.get("name")
        if isinstance(name, str):
            stripped = name.strip()
            if stripped:
                return stripped
    return None


def _same_group_id(value: object, league_team_id: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == league_team_id


class LeagueTeamProfileClient(Protocol):
    """Public profile read. ``PlanetsNuClient.load_profile`` is the production implementation."""

    def load_profile(self, username: str) -> dict[str, Any]: ...


class LeagueTeamDirectoryService:
    """Read league team names for one game, filling the durable id cache as names resolve."""

    def __init__(self, storage: StorageBackend, games: GameService) -> None:
        self._storage = storage
        self._games = games

    def teams_for_game(
        self,
        game_id: int,
        planets: LeagueTeamProfileClient,
    ) -> LeagueTeamsResponse:
        """Names for every distinct ``leagueteamid > 0`` on the stored roster.

        One profile fetch per uncached id. A failure or a missing row leaves that
        id unnamed and does not cache it, so a later read can try again. A cached
        id is not fetched.
        """
        players = self._games.get_game_info(game_id).players
        team_ids = sorted({player.leagueteamid for player in players if player.leagueteamid > 0})
        teams = [
            LeagueTeamName(
                id=team_id,
                name=self._name_for_team(team_id, players, planets),
            )
            for team_id in team_ids
        ]
        return LeagueTeamsResponse(teams=teams)

    def _name_for_team(
        self,
        league_team_id: int,
        players: list[Player],
        planets: LeagueTeamProfileClient,
    ) -> str | None:
        cached = self._cached_name(league_team_id)
        if cached is not None:
            return cached
        username = _probe_username(players, league_team_id)
        if username is None:
            return None
        try:
            profile = planets.load_profile(username)
        except UpstreamPlanetsError:
            logger.warning("League team %s profile fetch failed", league_team_id)
            return None
        name = league_team_name_from_profile(profile, league_team_id)
        if name is None:
            return None
        self._storage.put(
            league_team_store_key(league_team_id),
            {"id": league_team_id, "name": name},
        )
        return name

    def _cached_name(self, league_team_id: int) -> str | None:
        try:
            raw = self._storage.get(league_team_store_key(league_team_id))
        except NotFoundError:
            return None
        if not isinstance(raw, dict) or raw.get("id") != league_team_id:
            return None
        name = raw.get("name")
        if isinstance(name, str) and name.strip():
            return name
        return None


def _probe_username(players: list[Player], league_team_id: int) -> str | None:
    """Any member username for this id. The first non-blank roster row wins."""
    for player in players:
        if player.leagueteamid != league_team_id:
            continue
        username = player.username.strip()
        if username:
            return username
    return None
