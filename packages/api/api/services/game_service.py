"""Game service: read game info and turn data from the store."""
from api.models.game import GameInfo, TurnInfo
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json
from api.storage.base import StorageBackend


class GameService:
    """Service for reading game info and turn data.

    Reads raw JSON dicts from the storage backend and deserializes them
    into domain dataclasses.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def get_game_info(self, game_id: int) -> GameInfo:
        data = self._storage.get(f"games/{game_id}/info")
        return game_info_from_json(data)

    def get_turn_info(self, game_id: int, turn_number: int) -> TurnInfo:
        data = self._storage.get(f"games/{game_id}/turns/{turn_number}")
        return turn_info_from_json(data)
