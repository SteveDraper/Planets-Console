"""Turn document reads, enumeration, and Planets.nu ensure."""

from dacite.exceptions import DaciteError

from api.errors import (
    LoginCredentialsRequiredError,
    NotFoundError,
    UpstreamPlanetsError,
    ValidationError,
)
from api.models.game import TurnInfo
from api.models.planet import Planet
from api.planets_nu import PlanetsNuClient
from api.serialization.turn import turn_info_from_json
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.storage_json import require_dict
from api.storage.base import StorageBackend
from api.transport.game_info_update import RefreshGameInfoParams


class TurnLoadService:
    """Load ``TurnInfo`` from storage or Planets.nu upstream."""

    def __init__(
        self,
        storage: StorageBackend,
        credentials: CredentialService,
        games: GameService,
    ) -> None:
        self._storage = storage
        self._credentials = credentials
        self._games = games

    @staticmethod
    def _validate_turn_loaded_matches_request(
        game_id: int,
        turn_number: int,
        turn: TurnInfo,
    ) -> None:
        if turn.settings.turn != turn_number:
            raise UpstreamPlanetsError(
                f"Load turn response settings.turn ({turn.settings.turn}) does not match "
                f"requested turn ({turn_number})."
            )
        if turn.game.id != game_id:
            raise UpstreamPlanetsError(
                f"Load turn response game.id ({turn.game.id}) does not match "
                f"requested game id ({game_id})."
            )
        if turn.game.turn != turn_number:
            raise UpstreamPlanetsError(
                f"Load turn response game.turn ({turn.game.turn}) does not match "
                f"requested turn ({turn_number})."
            )

    def list_stored_turn_perspectives(self, game_id: int, turn_number: int) -> list[int]:
        """Return sorted 1-based perspective slots with turn data already in storage."""
        game_prefix = f"games/{game_id}"
        turn_label = str(turn_number)
        try:
            perspective_segments = self._storage.list(game_prefix)
        except NotFoundError:
            return []

        stored: list[int] = []
        for segment in perspective_segments:
            try:
                perspective = int(segment)
            except ValueError:
                continue
            if perspective < 1:
                continue
            turns_prefix = f"{game_prefix}/{perspective}/turns"
            try:
                turn_segments = self._storage.list(turns_prefix)
            except NotFoundError:
                continue
            if turn_label in turn_segments:
                stored.append(perspective)
        return sorted(stored)

    def get_turn_info(self, game_id: int, perspective: int, turn_number: int) -> TurnInfo:
        data = self._storage.get(f"games/{game_id}/{perspective}/turns/{turn_number}")
        return turn_info_from_json(
            require_dict(data, f"turn {turn_number} of game {game_id} perspective {perspective}")
        )

    def get_planet_from_turn(
        self, game_id: int, perspective: int, turn_number: int, planet_id: int
    ) -> Planet:
        turn = self.get_turn_info(game_id, perspective, turn_number)
        for planet in turn.planets:
            if planet.id == planet_id:
                return planet
        raise NotFoundError(
            f"No planet id {planet_id} in turn {turn_number} "
            f"(game {game_id}, perspective {perspective})."
        )

    def _player_id_for_perspective(self, game_id: int, perspective: int) -> int:
        info = self._games.get_game_info(game_id)
        return GameService.player_id_for_perspective(info, perspective, game_id)

    def ensure_turn_loaded(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        params: RefreshGameInfoParams,
        planets: PlanetsNuClient,
    ) -> TurnInfo:
        """Return turn data from storage, fetching from Planets.nu via loadturn when missing."""
        store_key = f"games/{game_id}/{perspective}/turns/{turn_number}"
        try:
            data = self._storage.get(store_key)
            return turn_info_from_json(
                require_dict(
                    data, f"turn {turn_number} of game {game_id} perspective {perspective}"
                )
            )
        except NotFoundError:
            pass

        if not params.username.strip():
            raise LoginCredentialsRequiredError(
                "Login name is required to load turn data when it is not already in storage."
            )

        player_id = self._player_id_for_perspective(game_id, perspective)

        if self._credentials.get_stored_api_key(params.username) is None:
            if params.password is None:
                raise LoginCredentialsRequiredError("Login credentials are required.")
            self._credentials.store_api_key(
                params.username,
                planets.login(params.username, params.password),
            )

        api_key = self._credentials.get_stored_api_key(params.username)
        if not api_key:
            raise LoginCredentialsRequiredError("Login credentials are required.")

        remote = planets.load_turn(
            game_id=game_id,
            turn=turn_number,
            player_id=player_id,
            api_key=api_key,
        )
        if not remote.get("success"):
            detail = remote.get("error") or remote.get("message") or "Load turn was not successful."
            raise UpstreamPlanetsError(str(detail))
        rst = remote.get("rst")
        if not isinstance(rst, dict):
            raise UpstreamPlanetsError(
                "Planets.nu loadturn response did not include an rst object."
            )

        try:
            turn = turn_info_from_json(rst)
        except DaciteError as err:
            raise ValidationError(
                "Load turn rst payload did not match the expected shape."
            ) from err

        self._validate_turn_loaded_matches_request(game_id, turn_number, turn)

        self._storage.put(store_key, rst)
        return turn
