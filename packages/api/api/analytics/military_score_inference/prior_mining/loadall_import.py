"""Loadall import helpers for inference prior mining."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from api.errors import NotFoundError
from api.models.game import GameInfo
from api.planets_nu import PlanetsNuClient
from api.serialization.game import game_info_from_json
from api.services.game_service import GameService
from api.services.load_all_archive import ArchiveTurnFile, parse_load_all_zip
from api.services.load_all_completeness import (
    blocking_finished_game_load_all_gaps,
    finished_game_load_all_gaps,
    is_finished_game_load_all_complete_for_prior_mining,
)
from api.services.load_all_final_turns import load_finished_game_final_turns
from api.services.storage_json import require_dict
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend
from api.transport.game_info_update import RefreshGameInfoParams

from .log import LOGGER

SPECTATOR_PLAYER_SLOT = 0


@dataclass(frozen=True)
class LoadAllImportResult:
    game_id: int
    imported: bool
    turns_written: int
    turns_skipped: int
    already_complete: bool
    final_turns_written: int = 0
    final_turns_skipped: int = 0
    final_turn_load_failures: tuple[int, ...] = ()


def ensure_game_info_stored(
    *,
    storage: StorageBackend,
    planets: PlanetsNuClient,
    game_id: int,
) -> GameInfo:
    store_key = f"games/{game_id}/info"
    try:
        raw = storage.get(store_key)
    except NotFoundError:
        raw = None
    if raw is None:
        LOGGER.info("game %s: downloading game info", game_id)
        remote = planets.load_game_info(game_id)
        storage.put(store_key, remote)
        raw = remote
    else:
        LOGGER.info("game %s: using stored game info", game_id)
    return game_info_from_json(require_dict(raw, f"game info {game_id}"))


def import_finished_game_loadall_if_needed(
    *,
    game_id: int,
    info: GameInfo,
    turn_load: TurnLoadService,
    planets: PlanetsNuClient,
    loadall_params: RefreshGameInfoParams | None = None,
) -> LoadAllImportResult:
    if not GameService.is_game_finished(info):
        return LoadAllImportResult(
            game_id=game_id,
            imported=False,
            turns_written=0,
            turns_skipped=0,
            already_complete=False,
        )

    if is_finished_game_load_all_complete_for_prior_mining(info, turn_load, game_id):
        LOGGER.info("game %s: turn set already complete enough for prior mining", game_id)
        return LoadAllImportResult(
            game_id=game_id,
            imported=False,
            turns_written=0,
            turns_skipped=0,
            already_complete=True,
        )

    LOGGER.info("game %s: downloading loadall archive", game_id)
    zip_bytes = planets.load_all(game_id)
    archive_turns = parse_load_all_zip(zip_bytes)
    grouped = _group_archive_turns_by_perspective(archive_turns)
    has_spectator_archive = SPECTATOR_PLAYER_SLOT in grouped

    turns_written = 0
    turns_skipped = 0
    latest_turn = info.game.turn
    player_count = len(info.players)

    spectator_entries = _archive_entries_for_spectator(latest_turn, grouped)
    for archive_turn in spectator_entries:
        if turn_load.store_archive_turn_if_missing(game_id, archive_turn):
            turns_written += 1
        else:
            turns_skipped += 1

    for perspective in range(1, player_count + 1):
        entries = _archive_entries_for_perspective(info, perspective, latest_turn, grouped)
        LOGGER.info(
            "game %s: importing perspective %s (%s turns)",
            game_id,
            perspective,
            len(entries),
        )
        for archive_turn in entries:
            if turn_load.store_archive_turn_if_missing(game_id, archive_turn):
                turns_written += 1
            else:
                turns_skipped += 1

    final_turns_written = 0
    final_turns_skipped = 0
    final_turn_failures: tuple[int, ...] = ()
    if loadall_params is not None:
        final_turn_result = load_finished_game_final_turns(
            turn_load,
            game_id,
            latest_turn,
            loadall_params,
            planets,
            player_count,
            include_spectator=has_spectator_archive,
        )
        final_turns_written = final_turn_result.turns_written
        final_turns_skipped = final_turn_result.turns_skipped
        final_turn_failures = tuple(sorted(final_turn_result.failures))
        turns_written += final_turns_written
        turns_skipped += final_turns_skipped
        if final_turn_failures:
            LOGGER.warning(
                "game %s: final turn load failed for perspectives %s",
                game_id,
                list(final_turn_failures),
            )
    elif blocking_finished_game_load_all_gaps(info, turn_load, game_id):
        LOGGER.warning(
            "game %s: turn set incomplete after archive import "
            "(more than the final turn is missing)",
            game_id,
        )
    elif finished_game_load_all_gaps(info, turn_load, game_id):
        LOGGER.info(
            "game %s: proceeding without final turn (not present in loadall archive)",
            game_id,
        )

    LOGGER.info(
        "game %s: loadall import complete (archive written=%s skipped=%s, "
        "final_turn written=%s skipped=%s)",
        game_id,
        turns_written - final_turns_written,
        turns_skipped - final_turns_skipped,
        final_turns_written,
        final_turns_skipped,
    )
    return LoadAllImportResult(
        game_id=game_id,
        imported=True,
        turns_written=turns_written,
        turns_skipped=turns_skipped,
        already_complete=False,
        final_turns_written=final_turns_written,
        final_turns_skipped=final_turns_skipped,
        final_turn_load_failures=final_turn_failures,
    )


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


def _archive_entries_for_spectator(
    latest_turn: int,
    grouped: dict[int, list[ArchiveTurnFile]],
) -> list[ArchiveTurnFile]:
    if latest_turn < 1:
        return []
    required = set(range(1, latest_turn + 1))
    return sorted(
        (
            entry
            for entry in grouped.get(SPECTATOR_PLAYER_SLOT, [])
            if entry.turn_number in required
        ),
        key=lambda item: item.turn_number,
    )


def _archive_entries_for_perspective(
    info: GameInfo,
    perspective: int,
    latest_turn: int,
    grouped: dict[int, list[ArchiveTurnFile]],
) -> list[ArchiveTurnFile]:
    from api.services.player_elimination import required_turn_numbers

    player = info.players[perspective - 1]
    required = set(required_turn_numbers(player, latest_turn))
    if not required:
        return []
    return sorted(
        (entry for entry in grouped.get(perspective, []) if entry.turn_number in required),
        key=lambda item: item.turn_number,
    )
