"""Game info reads and Planets.nu refresh."""

from dacite.exceptions import DaciteError

from api.errors import NotFoundError, ValidationError
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
from api.transport.sector_display import (
    sector_display_name_from_game_info,
    sector_display_name_from_stored_payload,
)

_sector_title_by_stored_game_id: dict[str, str | None] = {}


def clear_sector_title_cache() -> None:
    _sector_title_by_stored_game_id.clear()


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
        self._credentials.ensure_api_key_for_user(params.username, params.password, planets)

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
        self.remember_sector_title_for_game(game_id, info)
        return info

    def remember_sector_title_for_game(self, game_id: int, info: GameInfo) -> None:
        title = sector_display_name_from_game_info(info)
        _sector_title_by_stored_game_id[str(game_id)] = title

    def list_stored_games(self) -> dict[str, list[dict[str, str]]]:
        """Stored game ids with optional sector titles (cache or stored info)."""
        try:
            children = self._storage.list("games")
        except NotFoundError:
            return {"games": []}
        games: list[dict[str, str]] = []
        for child in children:
            game_id = str(child)
            entry: dict[str, str] = {"id": game_id}
            sector = self._resolved_sector_title_for_listed_game(game_id)
            if sector is not None:
                entry["sectorName"] = sector
            games.append(entry)
        return {"games": games}

    def _resolved_sector_title_for_listed_game(self, game_id: str) -> str | None:
        cached = _sector_title_by_stored_game_id.get(game_id)
        if cached is not None or game_id in _sector_title_by_stored_game_id:
            return cached

        try:
            raw = self._storage.get(f"games/{game_id}/info")
        except NotFoundError:
            title = None
        else:
            title = sector_display_name_from_stored_payload(raw)

        _sector_title_by_stored_game_id[game_id] = title
        return title

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
