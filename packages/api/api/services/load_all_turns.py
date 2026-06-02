"""Bulk load-all orchestration: archive import, status, and NDJSON progress."""

from collections import defaultdict
from collections.abc import Iterator

from api.errors import LoginCredentialsRequiredError
from api.models.game import GameInfo
from api.planets_nu import PlanetsNuClient
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_archive import ArchiveTurnFile, parse_load_all_zip
from api.services.load_all_final_turns import FinalTurnLoadResult, iter_final_turn_load_progress
from api.services.player_elimination import required_turn_numbers
from api.services.turn_load_service import TurnLoadService
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.load_all_turns import (
    LoadAllProgressUpdate,
    LoadAllStreamItem,
    LoadAllTurnsResponse,
    LoadAllTurnsStatusResponse,
)


def expected_perspectives_for_load_all(
    info: GameInfo, username: str, game_id: int
) -> list[int]:
    """1-based perspectives for load-all status and in-progress bulk load.

    Finished games require every player slot. In-progress games resolve the
    logged-in player's slot; empty or unknown usernames raise the same errors
    as ``iter_load_all_turns``.
    """
    if GameService.is_game_finished(info):
        return list(range(1, len(info.players) + 1))
    if not username.strip():
        raise LoginCredentialsRequiredError(
            "Login name is required to load turns from Planets.nu."
        )
    return [GameService.perspective_for_username(info, username, game_id)]


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

    def load_all_turns_status_for_user(
        self, game_id: int, username: str
    ) -> LoadAllTurnsStatusResponse:
        info = self._games.get_game_info(game_id)
        latest_turn = info.game.turn
        if latest_turn < 1:
            expected: list[int] = []
        else:
            expected = expected_perspectives_for_load_all(info, username, game_id)
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
        if latest_turn < 1:
            return True
        if not perspectives:
            return False
        for perspective in perspectives:
            player = info.players[perspective - 1]
            turns_required = required_turn_numbers(player, latest_turn)
            if not turns_required:
                continue
            stored = set(self._turns.list_stored_turn_numbers(game_id, perspective))
            for turn_number in turns_required:
                if turn_number not in stored:
                    return False
        return True

    @staticmethod
    def _archive_entries_for_perspective(
        info: GameInfo,
        perspective: int,
        latest_turn: int,
        grouped: dict[int, list[ArchiveTurnFile]],
    ) -> list[ArchiveTurnFile]:
        """Archive turns within the required range for this perspective (skips post-death)."""
        player = info.players[perspective - 1]
        required = set(required_turn_numbers(player, latest_turn))
        if not required:
            return []
        return sorted(
            (entry for entry in grouped.get(perspective, []) if entry.turn_number in required),
            key=lambda item: item.turn_number,
        )

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

        latest_turn = info.game.turn
        for perspective_index, perspective in enumerate(range(1, player_count + 1), start=1):
            entries = self._archive_entries_for_perspective(info, perspective, latest_turn, grouped)
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
        perspective = expected_perspectives_for_load_all(info, params.username, game_id)[0]
        latest_turn = info.game.turn
        player = info.players[perspective - 1]
        turns_to_load = required_turn_numbers(player, latest_turn)
        turns_written = 0
        turns_skipped = 0
        turn_total = max(len(turns_to_load), 1)
        for turn_index, turn_number in enumerate(turns_to_load, start=1):
            yield LoadAllProgressUpdate(
                phase="import",
                perspective=1,
                perspective_total=1,
                turn=turn_index,
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
