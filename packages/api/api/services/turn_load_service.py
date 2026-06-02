"""Turn document reads, enumeration, and Planets.nu ensure."""

import logging
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from dacite.exceptions import DaciteError, MissingValueError

from api.errors import (
    LoginCredentialsRequiredError,
    NotFoundError,
    UpstreamPlanetsError,
    ValidationError,
)
from api.models.game import GameInfo, TurnInfo
from api.models.planet import Planet
from api.planets_nu import PlanetsNuClient
from api.serialization.codecs import dataclass_deserialization_detail
from api.serialization.turn import turn_info_from_json
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_archive import ArchiveTurnFile, parse_load_all_zip
from api.services.storage_json import require_dict
from api.storage.base import StorageBackend
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.load_all_turns import (
    LoadAllProgressUpdate,
    LoadAllTurnsResponse,
    LoadAllTurnsStatusResponse,
)

logger = logging.getLogger(__name__)


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
        self._settings_defaults_by_game: dict[int, dict | None] = {}

    @staticmethod
    def _missing_settings_field_error(err: DaciteError) -> bool:
        if not isinstance(err, MissingValueError):
            return False
        path = err.field_path or ""
        return path == "settings" or path.startswith("settings.")

    def _game_settings_defaults(self, game_id: int) -> dict | None:
        """Settings from stored game info, used to backfill historical turn snapshots."""
        if game_id in self._settings_defaults_by_game:
            return self._settings_defaults_by_game[game_id]
        try:
            info = self._storage.get(f"games/{game_id}/info")
        except NotFoundError:
            defaults = None
        else:
            if not isinstance(info, dict):
                defaults = None
            else:
                settings = info.get("settings")
                defaults = settings if isinstance(settings, dict) else None
        self._settings_defaults_by_game[game_id] = defaults
        return defaults

    def _deserialize_turn_json(
        self,
        game_id: int,
        data: dict,
        *,
        settings_defaults: dict | None = None,
        error_prefix: str,
    ) -> TurnInfo:
        try:
            return turn_info_from_json(data, settings_defaults=settings_defaults)
        except DaciteError as first_err:
            if settings_defaults is not None or not self._missing_settings_field_error(first_err):
                raise ValidationError(
                    dataclass_deserialization_detail(error_prefix, first_err)
                ) from first_err
            defaults = self._game_settings_defaults(game_id)
            if defaults is None:
                raise ValidationError(
                    dataclass_deserialization_detail(error_prefix, first_err)
                ) from first_err
            try:
                return turn_info_from_json(data, settings_defaults=defaults)
            except DaciteError as err:
                raise ValidationError(dataclass_deserialization_detail(error_prefix, err)) from err

    def _turn_info_from_stored_json(self, game_id: int, data: dict) -> TurnInfo:
        return self._deserialize_turn_json(
            game_id,
            data,
            error_prefix="Stored turn payload did not match the expected shape",
        )

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
        """Return sorted perspective slots (0 or 1-based) with turn data already in storage."""
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
            if perspective < 0:
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
        return self._turn_info_from_stored_json(
            game_id,
            require_dict(data, f"turn {turn_number} of game {game_id} perspective {perspective}"),
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

    @staticmethod
    def _upstream_turn_for_load(
        perspective: int, turn_number: int, current_turn: int
    ) -> int | None:
        """Map a requested turn to the value sent to Planets.nu loadturn.

        Spectator (perspective 0) on the current turn must omit ``turn`` from the upstream
        request; ``playerid=0`` with an explicit current-turn number fails upstream with a
        server error, but omitting ``turn`` returns the latest turn. When stored game info is
        stale, that latest turn may not match ``turn_number``; ``ensure_turn_loaded`` then
        retries once with an explicit ``turn_number`` (which succeeds for historical turns).
        """
        if perspective == 0 and turn_number == current_turn:
            return None
        return turn_number

    def _load_turn_from_planets_upstream(
        self,
        *,
        game_id: int,
        player_id: int,
        upstream_turn: int | None,
        api_key: str,
        planets: PlanetsNuClient,
    ) -> tuple[dict, TurnInfo]:
        """Fetch one turn from Planets.nu and deserialize it."""
        remote = planets.load_turn(
            game_id=game_id,
            turn=upstream_turn,
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
        turn = self._deserialize_turn_json(
            game_id,
            rst,
            error_prefix="Load turn rst payload did not match the expected shape",
        )
        return rst, turn

    @staticmethod
    def _should_retry_spectator_turnless_with_explicit_turn(
        upstream_turn: int | None,
        game_id: int,
        turn_number: int,
        turn: TurnInfo,
    ) -> bool:
        if upstream_turn is not None:
            return False
        if turn.game.id != game_id:
            return False
        return turn.settings.turn != turn_number or turn.game.turn != turn_number

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
            return self._turn_info_from_stored_json(
                game_id,
                require_dict(
                    data, f"turn {turn_number} of game {game_id} perspective {perspective}"
                ),
            )
        except NotFoundError:
            pass

        if not params.username.strip():
            raise LoginCredentialsRequiredError(
                "Login name is required to load turn data when it is not already in storage."
            )

        game_info = self._games.get_game_info(game_id)
        player_id = GameService.player_id_for_perspective(game_info, perspective, game_id)
        upstream_turn = self._upstream_turn_for_load(perspective, turn_number, game_info.game.turn)

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

        rst, turn = self._load_turn_from_planets_upstream(
            game_id=game_id,
            player_id=player_id,
            upstream_turn=upstream_turn,
            api_key=api_key,
            planets=planets,
        )
        if self._should_retry_spectator_turnless_with_explicit_turn(
            upstream_turn, game_id, turn_number, turn
        ):
            rst, turn = self._load_turn_from_planets_upstream(
                game_id=game_id,
                player_id=player_id,
                upstream_turn=turn_number,
                api_key=api_key,
                planets=planets,
            )

        self._validate_turn_loaded_matches_request(game_id, turn_number, turn)

        self._storage.put(store_key, rst)
        return turn

    def list_stored_turn_numbers(self, game_id: int, perspective: int) -> list[int]:
        """Return sorted turn numbers already stored for a perspective."""
        turns_prefix = f"games/{game_id}/{perspective}/turns"
        try:
            turn_segments = self._storage.list(turns_prefix)
        except NotFoundError:
            return []
        stored: list[int] = []
        for segment in turn_segments:
            try:
                turn_number = int(segment)
            except ValueError:
                continue
            if turn_number >= 1:
                stored.append(turn_number)
        return sorted(stored)

    def expected_perspectives_for_load_all(self, info: GameInfo, username: str) -> list[int]:
        """Perspective slots that a full bulk load should populate."""
        if GameService.is_game_finished(info):
            return list(range(1, len(info.players) + 1))
        return [GameService.perspective_for_username(info, username, info.game.id)]

    def _expected_perspectives_for_status(self, info: GameInfo, username: str) -> list[int]:
        if GameService.is_game_finished(info):
            return list(range(1, len(info.players) + 1))
        if not username.strip():
            return []
        try:
            return [GameService.perspective_for_username(info, username, info.game.id)]
        except ValidationError:
            return []

    def load_all_turns_status_for_user(
        self, game_id: int, username: str
    ) -> LoadAllTurnsStatusResponse:
        info = self._games.get_game_info(game_id)
        latest_turn = info.game.turn
        expected = self._expected_perspectives_for_status(info, username)
        return LoadAllTurnsStatusResponse(
            game_id=game_id,
            complete=self._is_load_all_complete(info, expected, latest_turn, game_id),
            is_game_finished=GameService.is_game_finished(info),
            expected_perspectives=expected,
            latest_turn=latest_turn,
        )

    def _is_load_all_complete(
        self,
        info: GameInfo,
        perspectives: list[int],
        latest_turn: int,
        game_id: int,
    ) -> bool:
        if latest_turn < 1 or not perspectives:
            return True
        for perspective in perspectives:
            stored = set(self.list_stored_turn_numbers(game_id, perspective))
            for turn_number in range(1, latest_turn + 1):
                if turn_number not in stored:
                    return False
        return True

    def _persist_archive_turn(
        self,
        game_id: int,
        archive_turn: ArchiveTurnFile,
    ) -> bool:
        """Store one archive turn when missing. Returns True if a new blob was written."""
        perspective = archive_turn.player_slot
        turn_number = archive_turn.turn_number
        if turn_number < 1:
            return False
        store_key = f"games/{game_id}/{perspective}/turns/{turn_number}"
        try:
            self._storage.get(store_key)
            return False
        except NotFoundError:
            pass
        self._storage.put(store_key, archive_turn.rst)
        return True

    def _ensure_api_key(self, params: RefreshGameInfoParams, planets: PlanetsNuClient) -> str:
        if not params.username.strip():
            raise LoginCredentialsRequiredError(
                "Login name is required to load turns from Planets.nu."
            )
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
        return api_key

    @staticmethod
    def _group_archive_turns_by_perspective(
        archive_turns: list[ArchiveTurnFile],
    ) -> dict[int, list[ArchiveTurnFile]]:
        grouped: dict[int, list[ArchiveTurnFile]] = defaultdict(list)
        for entry in archive_turns:
            if entry.turn_number >= 1:
                grouped[entry.player_slot].append(entry)
        for entries in grouped.values():
            entries.sort(key=lambda item: item.turn_number)
        return grouped

    @staticmethod
    def _progress_event(update: LoadAllProgressUpdate) -> dict[str, Any]:
        return {"type": "progress", **update.model_dump()}

    def _iter_load_finished_game_from_loadall(
        self,
        game_id: int,
        info: GameInfo,
        params: RefreshGameInfoParams,
        planets: PlanetsNuClient,
    ) -> Iterator[LoadAllProgressUpdate | LoadAllTurnsResponse]:
        player_count = len(info.players)
        yield LoadAllProgressUpdate(
            phase="download",
            perspective=0,
            perspective_total=player_count,
            turn=0,
            turn_total=0,
            message="Downloading loadall archive",
        )
        zip_bytes = planets.load_all(game_id)
        archive_turns = parse_load_all_zip(zip_bytes)
        grouped = self._group_archive_turns_by_perspective(archive_turns)

        turns_written = 0
        turns_skipped = 0
        perspectives_touched: set[int] = set()

        for perspective_index, perspective in enumerate(range(1, player_count + 1), start=1):
            entries = grouped.get(perspective, [])
            turn_total = max(len(entries), 1)
            for turn_index, archive_turn in enumerate(entries, start=1):
                yield LoadAllProgressUpdate(
                    phase="import",
                    perspective=perspective_index,
                    perspective_total=player_count,
                    turn=turn_index,
                    turn_total=turn_total,
                    message=(
                        f"Perspective {perspective}, turn {archive_turn.turn_number}"
                    ),
                )
                if self._persist_archive_turn(game_id, archive_turn):
                    turns_written += 1
                    perspectives_touched.add(archive_turn.player_slot)
                else:
                    turns_skipped += 1

        latest_turn = info.game.turn
        final_turn_load_failures: list[int] = []
        for perspective_index, perspective in enumerate(range(1, player_count + 1), start=1):
            if latest_turn < 1:
                continue
            store_key = f"games/{game_id}/{perspective}/turns/{latest_turn}"
            try:
                self._storage.get(store_key)
                turns_skipped += 1
                yield LoadAllProgressUpdate(
                    phase="final_turn",
                    perspective=perspective_index,
                    perspective_total=player_count,
                    turn=1,
                    turn_total=1,
                    message=f"Final turn already stored (perspective {perspective})",
                )
                continue
            except NotFoundError:
                pass
            yield LoadAllProgressUpdate(
                phase="final_turn",
                perspective=perspective_index,
                perspective_total=player_count,
                turn=1,
                turn_total=1,
                message=f"Loading final turn for perspective {perspective}",
            )
            try:
                self.ensure_turn_loaded(game_id, perspective, latest_turn, params, planets)
            except (UpstreamPlanetsError, ValidationError) as exc:
                final_turn_load_failures.append(perspective)
                logger.warning(
                    "Loadall final turn %s for game %s perspective %s failed: %s",
                    latest_turn,
                    game_id,
                    perspective,
                    exc,
                )
                continue
            turns_written += 1
            perspectives_touched.add(perspective)

        yield LoadAllTurnsResponse(
            game_id=game_id,
            is_game_finished=True,
            turns_written=turns_written,
            turns_skipped=turns_skipped,
            perspectives_touched=sorted(perspectives_touched),
            final_turn_load_failures=sorted(final_turn_load_failures),
        )

    def _iter_load_in_progress_game(
        self,
        game_id: int,
        info: GameInfo,
        params: RefreshGameInfoParams,
        planets: PlanetsNuClient,
    ) -> Iterator[LoadAllProgressUpdate | LoadAllTurnsResponse]:
        perspective = GameService.perspective_for_username(info, params.username, game_id)
        latest_turn = info.game.turn
        turns_written = 0
        turns_skipped = 0
        turn_total = max(latest_turn, 1)
        for turn_number in range(1, latest_turn + 1):
            yield LoadAllProgressUpdate(
                phase="import",
                perspective=1,
                perspective_total=1,
                turn=turn_number,
                turn_total=turn_total,
                message=f"Turn {turn_number}",
            )
            store_key = f"games/{game_id}/{perspective}/turns/{turn_number}"
            try:
                self._storage.get(store_key)
                turns_skipped += 1
                continue
            except NotFoundError:
                pass
            self.ensure_turn_loaded(game_id, perspective, turn_number, params, planets)
            turns_written += 1
        yield LoadAllTurnsResponse(
            game_id=game_id,
            is_game_finished=False,
            turns_written=turns_written,
            turns_skipped=turns_skipped,
            perspectives_touched=[perspective],
        )

    def iter_load_all_turns(
        self,
        game_id: int,
        params: RefreshGameInfoParams,
        planets: PlanetsNuClient,
    ) -> Iterator[dict[str, Any]]:
        """Yield NDJSON stream events: progress updates and a final complete payload."""
        self._ensure_api_key(params, planets)
        info = self._games.get_game_info(game_id)
        if GameService.is_game_finished(info):
            iterator = self._iter_load_finished_game_from_loadall(
                game_id, info, params, planets
            )
        else:
            iterator = self._iter_load_in_progress_game(game_id, info, params, planets)

        for item in iterator:
            if isinstance(item, LoadAllProgressUpdate):
                yield self._progress_event(item)
            else:
                yield {"type": "complete", "result": item.model_dump()}

    def load_all_turns(
        self,
        game_id: int,
        params: RefreshGameInfoParams,
        planets: PlanetsNuClient,
    ) -> LoadAllTurnsResponse:
        """Populate storage with all turns (loadall ZIP when finished, else sequential loadturn)."""
        result: LoadAllTurnsResponse | None = None
        for event in self.iter_load_all_turns(game_id, params, planets):
            if event.get("type") == "complete":
                result = LoadAllTurnsResponse(**event["result"])
        if result is None:
            raise RuntimeError("load_all_turns completed without a result")
        return result
