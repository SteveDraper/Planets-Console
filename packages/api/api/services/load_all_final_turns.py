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


def iter_final_turn_load_progress(
    turns: TurnLoadService,
    game_id: int,
    latest_turn: int,
    params: RefreshGameInfoParams,
    planets: PlanetsNuClient,
    player_count: int,
    result: FinalTurnLoadResult,
) -> Iterator[LoadAllProgressUpdate]:
    """Yield final-turn phase progress and update ``result`` in place."""
    for perspective_index, perspective in enumerate(range(1, player_count + 1), start=1):
        if latest_turn < 1:
            continue
        if turns.is_turn_stored(game_id, perspective, latest_turn):
            result.turns_skipped += 1
            yield LoadAllProgressUpdate(
                phase="final_turn",
                perspective=perspective_index,
                perspective_total=player_count,
                turn=1,
                turn_total=1,
                message=f"Final turn already stored (perspective {perspective})",
            )
            continue
        yield LoadAllProgressUpdate(
            phase="final_turn",
            perspective=perspective_index,
            perspective_total=player_count,
            turn=1,
            turn_total=1,
            message=f"Loading final turn for perspective {perspective}",
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
            continue
        result.turns_written += 1
        result.perspectives_touched.add(perspective)


def load_missing_final_turns(
    turns: TurnLoadService,
    game_id: int,
    latest_turn: int,
    params: RefreshGameInfoParams,
    planets: PlanetsNuClient,
    player_count: int,
) -> list[int]:
    """Load missing final turns for every perspective; return failed 1-based slots."""
    result = FinalTurnLoadResult()
    for _ in iter_final_turn_load_progress(
        turns, game_id, latest_turn, params, planets, player_count, result
    ):
        pass
    return sorted(result.failures)
