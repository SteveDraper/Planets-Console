"""Load a perspective's stored span and pack one Territory movie."""

from __future__ import annotations

from api.analytics.territory_movie import build_territory_movie
from api.errors import NotFoundError, ValidationError
from api.models.game import GameInfo, TurnInfo
from api.models.player import Player
from api.services.game_service import GameService
from api.services.league_team_directory import LeagueTeamDirectoryService, LeagueTeamProfileClient
from api.services.turn_load_service import TurnLoadService
from api.transport.territory_movie import TerritoryMovieResponse


class TerritoryMovieService:
    """Pack turns 1 through ``GameInfo.game.turn`` for one perspective.

    A missing stored turn fails the request. This service does not fetch turns
    from Planets.nu. League team names come from the directory.
    """

    def __init__(
        self,
        games: GameService,
        turns: TurnLoadService,
        directory: LeagueTeamDirectoryService,
    ) -> None:
        self._games = games
        self._turns = turns
        self._directory = directory

    def for_perspective(
        self,
        game_id: int,
        perspective: int,
        planets: LeagueTeamProfileClient,
    ) -> TerritoryMovieResponse:
        info = self._games.get_game_info(game_id)
        end = info.game.turn
        if end < 1:
            raise ValidationError(f"Game {game_id} has no host turn to pack (game.turn is {end}).")
        stored = [self._stored_turn(game_id, perspective, number) for number in range(1, end + 1)]
        return build_territory_movie(
            stored,
            player_names=_player_names(info, stored),
            team_names=self._team_names(game_id, planets),
        )

    def _stored_turn(self, game_id: int, perspective: int, turn_number: int) -> TurnInfo:
        try:
            return self._turns.get_turn_info(game_id, perspective, turn_number)
        except NotFoundError as exc:
            raise NotFoundError(
                f"Stored turn {turn_number} is missing for game {game_id} "
                f"perspective {perspective}."
            ) from exc

    def _team_names(
        self,
        game_id: int,
        planets: LeagueTeamProfileClient,
    ) -> dict[int, str | None]:
        directory = self._directory.teams_for_game(game_id, planets)
        return {team.id: team.name for team in directory.teams}


def _player_names(info: GameInfo, turns: list[TurnInfo]) -> dict[int, str | None]:
    """Roster username for each player id. A blank name stays missing so a later row can fill it."""
    names: dict[int, str | None] = {}

    def consider(player: Player) -> None:
        if names.get(player.id):
            return
        stripped = player.username.strip()
        if stripped:
            names[player.id] = stripped
        elif player.id not in names:
            names[player.id] = None

    for player in info.players:
        consider(player)
    for turn in turns:
        for player in turn.players:
            consider(player)
        consider(turn.player)
    return names
