"""Final-turn loading after a finished-game loadall archive import."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

from api.errors import UpstreamPlanetsError, ValidationError
from api.planets_nu import PlanetsNuClient
from api.services.turn_load_service import TurnLoadService
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.load_all_turns import LoadAllProgressUpdate

logger = logging.getLogger(__name__)


@dataclass
class FinalTurnLoadResult:
    """Counters and failures accumulated while loading missing final turns."""

    turns_written: int = 0
    turns_skipped: int = 0
    perspectives_touched: set[int] = field(default_factory=set)
    failures: list[int] = field(default_factory=list)


def _yield_final_turn_for_perspective(
    turns: TurnLoadService,
    game_id: int,
    latest_turn: int,
    params: RefreshGameInfoParams,
    planets: PlanetsNuClient,
    *,
    perspective: int,
    perspective_index: int,
    perspective_total: int,
    result: FinalTurnLoadResult,
) -> Iterator[LoadAllProgressUpdate]:
    if latest_turn < 1:
        return
    if turns.is_turn_stored(game_id, perspective, latest_turn):
        result.turns_skipped += 1
        yield LoadAllProgressUpdate(
            phase="final_turn",
            perspective=perspective_index,
            perspective_total=perspective_total,
            turn=1,
            turn_total=1,
            message=(
                "Final turn already stored (spectator perspective)"
                if perspective == 0
                else f"Final turn already stored (perspective {perspective})"
            ),
        )
        return
    yield LoadAllProgressUpdate(
        phase="final_turn",
        perspective=perspective_index,
        perspective_total=perspective_total,
        turn=1,
        turn_total=1,
        message=(
            "Loading final turn for spectator perspective"
            if perspective == 0
            else f"Loading final turn for perspective {perspective}"
        ),
    )
    try:
        turns.ensure_turn_loaded(game_id, perspective, latest_turn, params, planets)
    except (UpstreamPlanetsError, ValidationError) as exc:
        result.failures.append(perspective)
        logger.warning(
            "Loadall final turn %s for game %s perspective %s failed: %s",
            latest_turn,
            game_id,
            perspective,
            exc,
        )
        return
    result.turns_written += 1
    result.perspectives_touched.add(perspective)


def load_finished_game_final_turns(
    turns: TurnLoadService,
    game_id: int,
    latest_turn: int,
    params: RefreshGameInfoParams,
    planets: PlanetsNuClient,
    player_count: int,
    *,
    include_spectator: bool = False,
) -> FinalTurnLoadResult:
    """Fetch and store any missing final turns after a loadall archive import."""
    result = FinalTurnLoadResult()
    for _ in iter_final_turn_load_progress(
        turns,
        game_id,
        latest_turn,
        params,
        planets,
        player_count,
        result,
        include_spectator=include_spectator,
    ):
        pass
    return result


def iter_final_turn_load_progress(
    turns: TurnLoadService,
    game_id: int,
    latest_turn: int,
    params: RefreshGameInfoParams,
    planets: PlanetsNuClient,
    player_count: int,
    result: FinalTurnLoadResult,
    *,
    include_spectator: bool = False,
) -> Iterator[LoadAllProgressUpdate]:
    """Yield final-turn phase progress and update ``result`` in place."""
    if include_spectator:
        yield from _yield_final_turn_for_perspective(
            turns,
            game_id,
            latest_turn,
            params,
            planets,
            perspective=0,
            perspective_index=0,
            perspective_total=player_count,
            result=result,
        )
    for perspective_index, perspective in enumerate(range(1, player_count + 1), start=1):
        yield from _yield_final_turn_for_perspective(
            turns,
            game_id,
            latest_turn,
            params,
            planets,
            perspective=perspective,
            perspective_index=perspective_index,
            perspective_total=player_count,
            result=result,
        )
