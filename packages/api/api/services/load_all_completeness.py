"""Load-all completeness checks for finished games."""

from __future__ import annotations

from dataclasses import dataclass

from api.models.game import GameInfo
from api.services.player_elimination import required_turn_numbers
from api.services.turn_load_service import TurnLoadService


@dataclass(frozen=True)
class LoadAllCompletenessGap:
    perspective: int
    username: str
    missing_turns: tuple[int, ...]


def finished_game_load_all_gaps(
    info: GameInfo,
    turn_load: TurnLoadService,
    game_id: int,
) -> tuple[LoadAllCompletenessGap, ...]:
    """Return missing required turns per player perspective, if any."""
    latest_turn = info.game.turn
    if latest_turn < 1:
        return ()
    gaps: list[LoadAllCompletenessGap] = []
    for perspective in range(1, len(info.players) + 1):
        player = info.players[perspective - 1]
        turns_required = required_turn_numbers(player, latest_turn)
        if not turns_required:
            continue
        stored = set(turn_load.list_stored_turn_numbers(game_id, perspective))
        missing = tuple(turn_number for turn_number in turns_required if turn_number not in stored)
        if missing:
            gaps.append(
                LoadAllCompletenessGap(
                    perspective=perspective,
                    username=player.username,
                    missing_turns=missing,
                )
            )
    return tuple(gaps)


def is_final_turn_only_gap(missing_turns: tuple[int, ...], latest_turn: int) -> bool:
    """True when the only missing required turn is the game's final turn."""
    return missing_turns == (latest_turn,)


def blocking_finished_game_load_all_gaps(
    info: GameInfo,
    turn_load: TurnLoadService,
    game_id: int,
) -> tuple[LoadAllCompletenessGap, ...]:
    """Gaps that are not explained by a missing loadall final turn."""
    latest_turn = info.game.turn
    return tuple(
        gap
        for gap in finished_game_load_all_gaps(info, turn_load, game_id)
        if not is_final_turn_only_gap(gap.missing_turns, latest_turn)
    )


def is_finished_game_load_all_complete(
    info: GameInfo,
    turn_load: TurnLoadService,
    game_id: int,
) -> bool:
    """Return whether every player slot has all required turns stored."""
    return not finished_game_load_all_gaps(info, turn_load, game_id)


def is_finished_game_load_all_complete_for_prior_mining(
    info: GameInfo,
    turn_load: TurnLoadService,
    game_id: int,
) -> bool:
    """Accept finished games when only the final turn is missing from loadall."""
    return not blocking_finished_game_load_all_gaps(info, turn_load, game_id)
