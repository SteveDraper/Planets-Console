"""Loadall import and completeness checks before prior mining extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.services.load_all_completeness import (
    blocking_finished_game_load_all_gaps,
    finished_game_load_all_gaps,
    is_final_turn_only_gap,
    is_finished_game_load_all_complete_for_prior_mining,
)
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend
from api.transport.game_info_update import RefreshGameInfoParams

from .loadall_import import ensure_game_info_stored, import_finished_game_loadall_if_needed
from .log import LOGGER

PrepareGameOutcome = Literal[
    "ready",
    "skipped_not_finished",
    "skipped_incomplete",
    "error",
]


@dataclass(frozen=True)
class IncompleteGapDetail:
    perspective: int
    username: str
    missing_turns: tuple[int, ...]


@dataclass(frozen=True)
class PrepareGameResult:
    game_id: int
    outcome: PrepareGameOutcome
    error_message: str | None = None
    incomplete_gaps: tuple[IncompleteGapDetail, ...] = ()
    turns_written: int = 0
    turns_skipped: int = 0
    imported: bool = False
    final_turn_only_gap_count: int = 0


def prepare_game_for_mining(
    *,
    game_id: int,
    storage: StorageBackend,
    turn_load: TurnLoadService,
    game_service: GameService,
    planets: PlanetsNuClient,
    loadall_params: RefreshGameInfoParams | None = None,
) -> PrepareGameResult:
    """Download loadall when needed, import turns, and verify mining completeness."""
    try:
        info = ensure_game_info_stored(storage=storage, planets=planets, game_id=game_id)
        if not GameService.is_game_finished(info):
            LOGGER.warning("game %s: skipped (not finished)", game_id)
            return PrepareGameResult(game_id=game_id, outcome="skipped_not_finished")

        import_result = import_finished_game_loadall_if_needed(
            game_id=game_id,
            info=info,
            turn_load=turn_load,
            planets=planets,
            loadall_params=loadall_params,
        )
        info = game_service.get_game_info(game_id)
        if not is_finished_game_load_all_complete_for_prior_mining(info, turn_load, game_id):
            gaps = blocking_finished_game_load_all_gaps(info, turn_load, game_id)
            for gap in gaps:
                LOGGER.warning(
                    "game %s: perspective %s (%s) missing turns %s",
                    game_id,
                    gap.perspective,
                    gap.username,
                    list(gap.missing_turns),
                )
            LOGGER.warning("game %s: skipped (incomplete turn set after import)", game_id)
            return PrepareGameResult(
                game_id=game_id,
                outcome="skipped_incomplete",
                incomplete_gaps=tuple(
                    IncompleteGapDetail(
                        perspective=gap.perspective,
                        username=gap.username,
                        missing_turns=tuple(gap.missing_turns),
                    )
                    for gap in gaps
                ),
                turns_written=import_result.turns_written,
                turns_skipped=import_result.turns_skipped,
                imported=import_result.imported,
            )

        final_turn_only_gaps = tuple(
            gap
            for gap in finished_game_load_all_gaps(info, turn_load, game_id)
            if is_final_turn_only_gap(gap.missing_turns, info.game.turn)
        )
        if final_turn_only_gaps:
            LOGGER.info(
                "game %s: mining without final turn for %s perspective(s)",
                game_id,
                len(final_turn_only_gaps),
            )
        if import_result.imported:
            LOGGER.info(
                "game %s: imported turns (written=%s skipped=%s)",
                game_id,
                import_result.turns_written,
                import_result.turns_skipped,
            )

        return PrepareGameResult(
            game_id=game_id,
            outcome="ready",
            turns_written=import_result.turns_written,
            turns_skipped=import_result.turns_skipped,
            imported=import_result.imported,
            final_turn_only_gap_count=len(final_turn_only_gaps),
        )
    except Exception as exc:  # noqa: BLE001 - isolate per-game prepare failures
        LOGGER.exception("game %s: prepare failed", game_id)
        return PrepareGameResult(
            game_id=game_id,
            outcome="error",
            error_message=str(exc),
        )
