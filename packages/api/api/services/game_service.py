"""Game service: read game info and turn data from the store."""

import re

from api.errors import (
    LoginCredentialsRequiredError,
    NotFoundError,
    UpstreamPlanetsError,
    ValidationError,
)
from api.models.game import GameInfo, TurnInfo
from api.models.game_info_operations import GameInfoUpdateOperation
from api.planets_nu import PlanetsNuClient
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json
from api.storage.base import JSONValue, StorageBackend
from api.transport.game_info_update import GameInfoUpdateRequest, RefreshGameInfoParams

_USERNAME_SAFE = re.compile(r"^[a-zA-Z0-9_.-]+$")


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

    def _credentials_api_key_path(self, username: str) -> str:
        if not username or not _USERNAME_SAFE.fullmatch(username):
            raise ValidationError(
                "username must be non-empty and contain only letters, digits, "
                "underscores, dots, and hyphens"
            )
        return f"credentials/accounts/{username}/api_key"

    def _get_stored_api_key(self, username: str) -> str | None:
        path = self._credentials_api_key_path(username)
        try:
            raw = self._storage.get(path)
        except NotFoundError:
            return None
        if isinstance(raw, str) and raw.strip():
            return raw
        return None

    def _store_api_key(self, username: str, api_key: str) -> None:
        self._storage.put(self._credentials_api_key_path(username), api_key)

    @staticmethod
    def _current_turn_from_game_info_dict(payload: dict) -> int:
        game = payload.get("game")
        if isinstance(game, dict) and "turn" in game:
            return int(game["turn"])
        settings = payload.get("settings")
        if isinstance(settings, dict) and "turn" in settings:
            return int(settings["turn"])
        raise ValidationError("Refreshed game info did not contain a current turn.")

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
        if self._get_stored_api_key(params.username) is None:
            if params.password is None:
                raise LoginCredentialsRequiredError("Login credentials are required.")
            self._store_api_key(params.username, planets.login(params.username, params.password))

        remote = planets.load_game_info(game_id)
        game_obj = remote.get("game")
        if not isinstance(game_obj, dict):
            raise ValidationError("Loaded game info did not include a game object.")
        remote_id = game_obj.get("id")
        if remote_id is None or int(remote_id) != game_id:
            raise ValidationError("Loaded game info does not match the requested game id.")

        store_key = f"games/{game_id}/info"
        self._storage.put(store_key, remote)
        _ = self._current_turn_from_game_info_dict(remote)
        return game_info_from_json(_require_dict(remote, f"game info {game_id}"))

    def get_game_info(self, game_id: int) -> GameInfo:
        data = self._storage.get(f"games/{game_id}/info")
        return game_info_from_json(_require_dict(data, f"game info {game_id}"))

    def get_turn_info(self, game_id: int, perspective: int, turn_number: int) -> TurnInfo:
        data = self._storage.get(f"games/{game_id}/{perspective}/turns/{turn_number}")
        return turn_info_from_json(
            _require_dict(data, f"turn {turn_number} of game {game_id} perspective {perspective}")
        )

    def _player_id_for_perspective(self, game_id: int, perspective: int) -> int:
        info_raw = self._storage.get(f"games/{game_id}/info")
        info_dict = _require_dict(info_raw, f"game info {game_id}")
        players = info_dict.get("players")
        if not isinstance(players, list) or perspective < 1 or perspective > len(players):
            raise ValidationError(
                f"Invalid perspective {perspective} for game {game_id} "
                "(check game info players list)."
            )
        entry = players[perspective - 1]
        if not isinstance(entry, dict):
            raise ValidationError(f"Game info players[{perspective - 1}] is not an object.")
        raw_id = entry.get("id")
        if raw_id is None:
            raise ValidationError(f"Game info players[{perspective - 1}] has no id.")
        return int(raw_id)

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
                _require_dict(
                    data, f"turn {turn_number} of game {game_id} perspective {perspective}"
                )
            )
        except NotFoundError:
            pass

        player_id = self._player_id_for_perspective(game_id, perspective)

        if self._get_stored_api_key(params.username) is None:
            if params.password is None:
                raise LoginCredentialsRequiredError("Login credentials are required.")
            self._store_api_key(params.username, planets.login(params.username, params.password))

        api_key = self._get_stored_api_key(params.username)
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

        self._storage.put(store_key, rst)
        return turn_info_from_json(
            _require_dict(rst, f"turn {turn_number} of game {game_id} perspective {perspective}")
        )

    def get_map_base(self, game_id: int, perspective: int, turn_number: int) -> dict:
        """Return base-map data derived from the planets in a turn.

        Base-map is the fixed layer used by the frontend map view. For now:
        - nodes represent planets (no edges yet)
        - node id and label are both `p{id}` (stable, independent of turn name data)
        """
        turn = self.get_turn_info(game_id, perspective, turn_number)
        nodes = [{"id": f"p{p.id}", "label": f"p{p.id}", "x": p.x, "y": p.y} for p in turn.planets]
        return {"analyticId": "base-map", "nodes": nodes, "edges": []}

    def get_turn_analytics(
        self, game_id: int, perspective: int, turn_number: int, analytic_id: str
    ) -> dict:
        """Return per-analytic map data derived from turn state.

        This keeps the "analytic_id -> data" pattern in Core, so the BFF can treat
        base-map like any other analytic.
        """
        if analytic_id == "base-map":
            return self.get_map_base(game_id, perspective, turn_number)
        # Unknown analytic: treat as validation error so the BFF can decide whether
        # to surface 404/422 vs fallback. This raises ValidationError, which maps to HTTP 422.
        raise ValidationError(f"Unknown analytic_id: {analytic_id!r}")
