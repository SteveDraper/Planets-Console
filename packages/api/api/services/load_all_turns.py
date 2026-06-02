"""Bulk load-all orchestration: archive import, status, and NDJSON progress."""

from collections import defaultdict
from collections.abc import Iterator

from api.errors import (
    LoginCredentialsRequiredError,
    ValidationError,
)
from api.models.game import GameInfo
from api.planets_nu import PlanetsNuClient
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_archive import ArchiveTurnFile, parse_load_all_zip
from api.services.load_all_final_turns import FinalTurnLoadResult, iter_final_turn_load_progress
from api.services.player_elimination import last_meaningful_turn
from api.services.turn_load_service import TurnLoadService
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.load_all_turns import (
    LoadAllProgressUpdate,
    LoadAllStreamItem,
    LoadAllTurnsResponse,
    LoadAllTurnsStatusResponse,
)


class LoadAllTurnsService:
    """Orchestrate bulk turn loading (loadall ZIP or sequential loadturn)."""

    def __init__(
        self,
        credentials: CredentialService,
        games: GameService,
        turns: TurnLoadService,
    ) -> None:
        self._credentials = credentials
        self._games = games
        self._turns = turns

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

    def _last_required_turn_for_perspective(
        self,
        info: GameInfo,
        perspective: int,
        latest_turn: int,
    ) -> int:
        """Highest turn number that must be stored for this perspective."""
        player = info.players[perspective - 1]
        return last_meaningful_turn(player, latest_turn)

    def _is_load_all_complete(
        self,
        info: GameInfo,
        perspectives: list[int],
        latest_turn: int,
        game_id: int,
    ) -> bool:
        if latest_turn < 1:
            return True
        if not perspectives:
            return False
        for perspective in perspectives:
            last_required = self._last_required_turn_for_perspective(info, perspective, latest_turn)
            if last_required < 1:
                continue
            stored = set(self._turns.list_stored_turn_numbers(game_id, perspective))
            for turn_number in range(1, last_required + 1):
                if turn_number not in stored:
                    return False
        return True

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
                    message=(f"Perspective {perspective}, turn {archive_turn.turn_number}"),
                )
                if self._turns.store_archive_turn_if_missing(game_id, archive_turn):
                    turns_written += 1
                    perspectives_touched.add(archive_turn.player_slot)
                else:
                    turns_skipped += 1

        latest_turn = info.game.turn
        final_turn_result = FinalTurnLoadResult()
        yield from iter_final_turn_load_progress(
            self._turns,
            game_id,
            latest_turn,
            params,
            planets,
            player_count,
            final_turn_result,
        )
        turns_written += final_turn_result.turns_written
        turns_skipped += final_turn_result.turns_skipped
        perspectives_touched |= final_turn_result.perspectives_touched

        yield LoadAllTurnsResponse(
            game_id=game_id,
            is_game_finished=True,
            turns_written=turns_written,
            turns_skipped=turns_skipped,
            perspectives_touched=sorted(perspectives_touched),
            final_turn_load_failures=sorted(final_turn_result.failures),
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
            if self._turns.is_turn_stored(game_id, perspective, turn_number):
                turns_skipped += 1
                continue
            self._turns.ensure_turn_loaded(game_id, perspective, turn_number, params, planets)
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
    ) -> Iterator[LoadAllStreamItem]:
        """Yield progress updates and a final summary (serialize to NDJSON in routers)."""
        if not params.username.strip():
            raise LoginCredentialsRequiredError(
                "Login name is required to load turns from Planets.nu."
            )
        self._credentials.ensure_api_key_for_user(params.username, params.password, planets)
        info = self._games.get_game_info(game_id)
        if GameService.is_game_finished(info):
            yield from self._iter_load_finished_game_from_loadall(game_id, info, params, planets)
        else:
            yield from self._iter_load_in_progress_game(game_id, info, params, planets)
