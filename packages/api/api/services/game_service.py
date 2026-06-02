"""Game info reads and Planets.nu refresh."""

from dacite.exceptions import DaciteError

from api.errors import LoginCredentialsRequiredError, ValidationError
from api.models.enums import GameStatus
from api.models.game import GameInfo
from api.models.game_info_operations import GameInfoUpdateOperation
from api.planets_nu import PlanetsNuClient
from api.serialization.codecs import dataclass_deserialization_detail
from api.serialization.game import game_info_from_json
from api.services.credential_service import CredentialService
from api.services.storage_json import require_dict
from api.storage.base import StorageBackend
from api.transport.game_info_update import GameInfoUpdateRequest, RefreshGameInfoParams


class GameService:
    """Load and refresh ``GameInfo`` documents at ``games/{gameId}/info``."""

    def __init__(
        self,
        storage: StorageBackend,
        credentials: CredentialService | None = None,
    ) -> None:
        self._storage = storage
        self._credentials = credentials or CredentialService(storage)

    @staticmethod
    def is_game_finished(info: GameInfo) -> bool:
        return info.game.status == GameStatus.FINISHED

    @staticmethod
    def perspective_for_username(info: GameInfo, username: str, game_id: int) -> int:
        """1-based perspective slot for a player username; raises if not in the game."""
        needle = username.strip().lower()
        if not needle:
            raise ValidationError("username is required to resolve the player perspective.")
        for index, player in enumerate(info.players):
            if player.username.strip().lower() == needle:
                return index + 1
        raise ValidationError(f"Login {username!r} is not a player in game {game_id}.")

    @staticmethod
    def player_id_for_perspective(info: GameInfo, perspective: int, game_id: int) -> int:
        if perspective == 0:
            return 0
        players = info.players
        if perspective < 1 or perspective > len(players):
            raise ValidationError(
                f"Invalid perspective {perspective} for game {game_id} "
                "(check game info players list)."
            )
        return players[perspective - 1].id

    @staticmethod
    def _validate_refreshed_game_info_has_current_turn(info: GameInfo) -> None:
        if info.game.turn != info.settings.turn:
            raise ValidationError(
                "Refreshed game info has inconsistent game.turn and settings.turn."
            )

    def update_game_info(
        self, game_id: int, body: GameInfoUpdateRequest, planets: PlanetsNuClient
    ) -> GameInfo:
        if body.operation != GameInfoUpdateOperation.REFRESH:
            raise ValidationError(f"Unsupported operation: {body.operation!r}")
        params = RefreshGameInfoParams.model_validate(body.params)
        return self.refresh_game_info(game_id, params, planets)

    def refresh_game_info(
        self, game_id: int, params: RefreshGameInfoParams, planets: PlanetsNuClient
    ) -> GameInfo:
        if not params.username.strip():
            raise ValidationError("username is required to refresh game info.")
        if self._credentials.get_stored_api_key(params.username) is None:
            if params.password is None:
                raise LoginCredentialsRequiredError("Login credentials are required.")
            self._credentials.store_api_key(
                params.username,
                planets.login(params.username, params.password),
            )

        remote = planets.load_game_info(game_id)
        try:
            info = game_info_from_json(require_dict(remote, f"game info {game_id}"))
        except DaciteError as err:
            raise ValidationError(
                dataclass_deserialization_detail(
                    "Loaded game info payload did not match the expected shape", err
                )
            ) from err

        if info.game.id != game_id:
            raise ValidationError("Loaded game info does not match the requested game id.")

        self._validate_refreshed_game_info_has_current_turn(info)

        store_key = f"games/{game_id}/info"
        self._storage.put(store_key, remote)
        return info

    def get_game_info(self, game_id: int) -> GameInfo:
        data = self._storage.get(f"games/{game_id}/info")
        try:
            return game_info_from_json(require_dict(data, f"game info {game_id}"))
        except DaciteError as err:
            raise ValidationError(
                dataclass_deserialization_detail(
                    "Stored game info did not match the expected shape", err
                )
            ) from err
