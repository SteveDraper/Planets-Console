"""Game service: read game info and turn data from the store."""

import re

from dacite.exceptions import DaciteError

from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.base_map import get_base_map
from api.analytics.scores import get_scores_table
from api.concepts.planet_connections import FlareConnectionMode
from api.concepts.warp_well import (
    WarpWellKind,
    coordinate_in_warp_well,
    map_cell_indices_in_warp_well,
)
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.errors import (
    LoginCredentialsRequiredError,
    NotFoundError,
    UpstreamPlanetsError,
    ValidationError,
)
from api.models.game import GameInfo, TurnInfo
from api.models.game_info_operations import GameInfoUpdateOperation
from api.models.planet import Planet
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
    def _validate_refreshed_game_info_has_current_turn(info: GameInfo) -> None:
        """Ensure game.turn and settings.turn agree before persisting a refresh.

        Successful ``game_info_from_json`` already required both fields; this rejects
        inconsistent upstream payloads.
        """
        if info.game.turn != info.settings.turn:
            raise ValidationError(
                "Refreshed game info has inconsistent game.turn and settings.turn."
            )

    @staticmethod
    def _validate_turn_loaded_matches_request(
        game_id: int,
        turn_number: int,
        turn: TurnInfo,
    ) -> None:
        """Ensure deserialized turn matches the requested game and turn before persisting.

        Prevents storing a response under ``.../turns/{N}`` when the payload is for
        another turn or game (bad upstream or stale cache).
        """
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

    @staticmethod
    def _player_id_for_perspective_from_game_info(
        info: GameInfo,
        perspective: int,
        game_id: int,
    ) -> int:
        players = info.players
        if perspective < 1 or perspective > len(players):
            raise ValidationError(
                f"Invalid perspective {perspective} for game {game_id} "
                "(check game info players list)."
            )
        return players[perspective - 1].id

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
        if self._get_stored_api_key(params.username) is None:
            if params.password is None:
                raise LoginCredentialsRequiredError("Login credentials are required.")
            self._store_api_key(params.username, planets.login(params.username, params.password))

        remote = planets.load_game_info(game_id)
        try:
            info = game_info_from_json(_require_dict(remote, f"game info {game_id}"))
        except DaciteError as err:
            raise ValidationError(
                "Loaded game info payload did not match the expected shape."
            ) from err

        if info.game.id != game_id:
            raise ValidationError("Loaded game info does not match the requested game id.")

        self._validate_refreshed_game_info_has_current_turn(info)

        store_key = f"games/{game_id}/info"
        self._storage.put(store_key, remote)
        return info

    def get_game_info(self, game_id: int) -> GameInfo:
        data = self._storage.get(f"games/{game_id}/info")
        return game_info_from_json(_require_dict(data, f"game info {game_id}"))

    def list_stored_turn_perspectives(self, game_id: int, turn_number: int) -> list[int]:
        """Return sorted 1-based perspective slots with turn data already in storage."""
        game_prefix = f"games/{game_id}"
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
            turn_path = f"{game_prefix}/{perspective}/turns/{turn_number}"
            try:
                self._storage.get(turn_path)
            except NotFoundError:
                continue
            stored.append(perspective)
        return sorted(stored)

    def get_turn_info(self, game_id: int, perspective: int, turn_number: int) -> TurnInfo:
        data = self._storage.get(f"games/{game_id}/{perspective}/turns/{turn_number}")
        return turn_info_from_json(
            _require_dict(data, f"turn {turn_number} of game {game_id} perspective {perspective}")
        )

    def get_planet_from_turn(
        self, game_id: int, perspective: int, turn_number: int, planet_id: int
    ) -> Planet:
        turn = self.get_turn_info(game_id, perspective, turn_number)
        for p in turn.planets:
            if p.id == planet_id:
                return p
        raise NotFoundError(
            f"No planet id {planet_id} in turn {turn_number} "
            f"(game {game_id}, perspective {perspective})."
        )

    def warp_well_coordinate_in_well(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        planet_id: int,
        map_x: float,
        map_y: float,
        well_kind: WarpWellKind,
    ) -> bool:
        planet = self.get_planet_from_turn(game_id, perspective, turn_number, planet_id)
        return coordinate_in_warp_well(planet, map_x, map_y, well_kind)

    def warp_well_cells(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        planet_id: int,
        well_kind: WarpWellKind,
    ) -> list[dict[str, int]]:
        planet = self.get_planet_from_turn(game_id, perspective, turn_number, planet_id)
        return [{"x": gx, "y": gy} for gx, gy in map_cell_indices_in_warp_well(planet, well_kind)]

    def _player_id_for_perspective(self, game_id: int, perspective: int) -> int:
        info = self.get_game_info(game_id)
        return GameService._player_id_for_perspective_from_game_info(info, perspective, game_id)

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

        if not params.username.strip():
            raise LoginCredentialsRequiredError(
                "Login name is required to load turn data when it is not already in storage."
            )

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

        try:
            turn = turn_info_from_json(rst)
        except DaciteError as err:
            raise ValidationError(
                "Load turn rst payload did not match the expected shape."
            ) from err

        self._validate_turn_loaded_matches_request(game_id, turn_number, turn)

        self._storage.put(store_key, rst)
        return turn

    def get_map_base(self, game_id: int, perspective: int, turn_number: int) -> dict:
        """Return base-map data derived from the planets in a turn."""
        turn = self.get_turn_info(game_id, perspective, turn_number)
        return get_base_map(turn)

    def get_scores_table(self, game_id: int, perspective: int, turn_number: int) -> dict:
        """Return scoreboard values for each player in a turn."""
        turn = self.get_turn_info(game_id, perspective, turn_number)
        return get_scores_table(turn)

    def get_turn_analytics(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        analytic_id: str,
        *,
        connection_warp_speed: int | None = None,
        connection_gravitonic_movement: bool = False,
        connection_flare_mode: FlareConnectionMode | str = FlareConnectionMode.OFF,
        connection_flare_depth: int = 1,
        connection_include_illustrative_routes: bool = False,
        diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
    ) -> dict:
        """Return per-analytic map data derived from turn state.

        This keeps the "analytic_id -> data" pattern in Core, so the BFF can treat
        base-map like any other analytic.
        """
        turn = self.get_turn_info(game_id, perspective, turn_number)
        return get_turn_analytic(
            analytic_id,
            turn,
            TurnAnalyticsOptions(
                connection_warp_speed=connection_warp_speed,
                connection_gravitonic_movement=connection_gravitonic_movement,
                connection_flare_mode=connection_flare_mode,
                connection_flare_depth=connection_flare_depth,
                connection_include_illustrative_routes=connection_include_illustrative_routes,
                diagnostics=diagnostics,
            ),
        )
