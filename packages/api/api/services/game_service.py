"""Game service: read game info and turn data from the store."""

from api.errors import ValidationError
from api.models.game import GameInfo, TurnInfo
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json
from api.storage.base import JSONValue, StorageBackend


def _require_dict(data: JSONValue, label: str) -> dict:
    if not isinstance(data, dict):
        raise ValidationError(f"Expected JSON object for {label}, got {type(data).__name__}")
    return data


class GameService:
    """Service for reading game info and turn data.

    Reads raw JSON dicts from the storage backend and deserializes them
    into domain dataclasses.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def get_game_info(self, game_id: int) -> GameInfo:
        data = self._storage.get(f"games/{game_id}/info")
        return game_info_from_json(_require_dict(data, f"game info {game_id}"))

    def get_turn_info(self, game_id: int, turn_number: int) -> TurnInfo:
        data = self._storage.get(f"games/{game_id}/turns/{turn_number}")
        return turn_info_from_json(_require_dict(data, f"turn {turn_number} of game {game_id}"))

    def get_map_base(self, game_id: int, turn_number: int) -> dict:
        """Return base-map data derived from the planets in a turn.

        Base-map is the fixed layer used by the frontend map view. For now:
        - nodes represent planets (no edges yet)
        - node ids are prefixed as `p{id}`
        """
        turn = self.get_turn_info(game_id, turn_number)
        nodes = [{"id": f"p{p.id}", "label": p.name, "x": p.x, "y": p.y} for p in turn.planets]
        return {"analyticId": "base-map", "nodes": nodes, "edges": []}

    def get_turn_analytics(self, game_id: int, turn_number: int, analytic_id: str) -> dict:
        """Return per-analytic map data derived from turn state.

        This keeps the "analytic_id -> data" pattern in Core, so the BFF can treat
        base-map like any other analytic.
        """
        if analytic_id == "base-map":
            return self.get_map_base(game_id, turn_number)
        # Unknown analytic: treat as validation error so the BFF can decide whether
        # to surface 404/422 vs fallback. For now, match FastAPI's default 404 style.
        raise ValidationError(f"Unknown analytic_id: {analytic_id!r}")
