"""Time one live scores ``tier_solve`` ``Solve()`` against a caller-supplied store."""

from __future__ import annotations

import time
from dataclasses import dataclass

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_admission import (
    resolve_inference_admission_skip,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.compute_orchestration import run_scores_tier_solve
from api.analytics.scores.tier_row_run_registry import (
    clear_row_runs,
    register_row_run,
)
from api.compute.sat_gil_overlap import (
    GIL_MIN_SOLVE_WALL_SECONDS,
    SatGilOverlap,
    capture_cp_sat_solve_overlap,
)
from api.errors import NotFoundError
from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json
from api.services.storage_json import require_dict
from api.services.turn_load_service import TurnLoadService
from api.storage.base import StorageBackend

SCORES_SOLVE_GAME_ID = 683364
SCORES_SOLVE_PERSPECTIVE = 1
SCORES_SOLVE_TURN = 27
SCORES_SOLVE_MAX_TIER_STEPS = 5


@dataclass(frozen=True)
class ScoresTierSolveTiming:
    """Walls for ``run_scores_tier_solve`` plus the longest inner ``Solve()``."""

    game_id: int
    perspective: int
    turn: int
    player_id: int
    tier_wall_seconds: float
    step_outcome: str
    solve_invoked: bool
    solve_count: int
    python_progressed_during_solve: bool | None
    overlap_fraction: float | None
    solve_wall_seconds: float | None
    solve_status: str | None
    spin_increments: int | None

    def to_probe_json(self) -> dict[str, int | float | bool | str | None]:
        """Wire object for ``--console-package-probe`` (uv vs frozen comparison)."""
        return {
            "gameId": self.game_id,
            "perspective": self.perspective,
            "turn": self.turn,
            "playerId": self.player_id,
            "tierWallSeconds": self.tier_wall_seconds,
            "stepOutcome": self.step_outcome,
            "solveInvoked": self.solve_invoked,
            "solveCount": self.solve_count,
            "pythonProgressedDuringSolve": self.python_progressed_during_solve,
            "overlapFraction": self.overlap_fraction,
            "solveWallSeconds": self.solve_wall_seconds,
            "solveStatus": self.solve_status,
            "spinIncrements": self.spin_increments,
        }


def time_scores_tier_solve_jobs(
    storage: StorageBackend,
    *,
    game_id: int = SCORES_SOLVE_GAME_ID,
    perspective: int = SCORES_SOLVE_PERSPECTIVE,
    turn_number: int = SCORES_SOLVE_TURN,
    player_id: int | None = None,
) -> ScoresTierSolveTiming:
    """Run scores ``tier_solve`` and time CP-SAT ``Solve()`` GIL overlap.

    Walks admissible rows until a ``Solve()`` lasts at least
    ``GIL_MIN_SOLVE_WALL_SECONDS``, otherwise returns the longest captured
    solve. Reads an existing game tree via ``storage``. Does not persist.
    """
    turn = _load_turn(storage, game_id, perspective, turn_number)
    candidates = (
        (player_id,)
        if player_id is not None
        else _admissible_player_ids(turn, perspective=perspective)
    )
    best: ScoresTierSolveTiming | None = None
    for target_player_id in candidates:
        timing = _time_player_tier_solves(
            storage,
            turn,
            game_id=game_id,
            perspective=perspective,
            player_id=target_player_id,
        )
        best = _prefer_timing(best, timing)
        if (timing.solve_wall_seconds or 0.0) >= GIL_MIN_SOLVE_WALL_SECONDS:
            return timing
    if best is not None:
        return best
    raise RuntimeError("no admissible scores row for tier_solve probe")


def _prefer_timing(
    current: ScoresTierSolveTiming | None,
    candidate: ScoresTierSolveTiming,
) -> ScoresTierSolveTiming:
    if current is None:
        return candidate
    if candidate.solve_invoked and not current.solve_invoked:
        return candidate
    if candidate.solve_invoked and current.solve_invoked:
        if (candidate.solve_wall_seconds or 0.0) > (current.solve_wall_seconds or 0.0):
            return candidate
    return current


def _time_player_tier_solves(
    storage: StorageBackend,
    turn: TurnInfo,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
) -> ScoresTierSolveTiming:
    score = next(row for row in turn.scores if row.ownerid == player_id)

    def load_scoreboard_turn(host_turn: int) -> TurnInfo | None:
        try:
            return _load_turn(storage, game_id, perspective, host_turn)
        except NotFoundError:
            return None

    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(
            score,
            turn,
            load_scoreboard_turn=load_scoreboard_turn,
        ),
        turn=turn,
        game_id=game_id,
        perspective=perspective,
        turn_number=turn.settings.turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    run = RowRun(session)
    register_row_run(run)
    try:
        with capture_cp_sat_solve_overlap() as captures:
            started = time.perf_counter()
            result = run_scores_tier_solve({"runId": run.run_id})
            steps = 1
            while (
                result.outcome == "continue"
                and steps < SCORES_SOLVE_MAX_TIER_STEPS
                and _longest_solve_wall(captures) < GIL_MIN_SOLVE_WALL_SECONDS
            ):
                result = run_scores_tier_solve({"runId": run.run_id})
                steps += 1
            tier_wall_seconds = time.perf_counter() - started
    finally:
        clear_row_runs()

    overlap = _longest_overlap(captures)
    return _timing_from_overlap(
        game_id=game_id,
        perspective=perspective,
        turn_number=turn.settings.turn,
        player_id=player_id,
        tier_wall_seconds=tier_wall_seconds,
        step_outcome=result.outcome,
        overlap=overlap,
        solve_count=len(captures),
    )


def _longest_solve_wall(captures: list[SatGilOverlap]) -> float:
    if not captures:
        return 0.0
    return max(item.solve_wall_seconds for item in captures)


def _longest_overlap(captures: list[SatGilOverlap]) -> SatGilOverlap | None:
    if not captures:
        return None
    return max(captures, key=lambda item: item.solve_wall_seconds)


def _timing_from_overlap(
    *,
    game_id: int,
    perspective: int,
    turn_number: int,
    player_id: int,
    tier_wall_seconds: float,
    step_outcome: str,
    overlap: SatGilOverlap | None,
    solve_count: int,
) -> ScoresTierSolveTiming:
    return ScoresTierSolveTiming(
        game_id=game_id,
        perspective=perspective,
        turn=turn_number,
        player_id=player_id,
        tier_wall_seconds=tier_wall_seconds,
        step_outcome=step_outcome,
        solve_invoked=overlap is not None,
        solve_count=solve_count,
        python_progressed_during_solve=(
            None if overlap is None else overlap.python_progressed_during_solve
        ),
        overlap_fraction=None if overlap is None else overlap.overlap_fraction,
        solve_wall_seconds=None if overlap is None else overlap.solve_wall_seconds,
        solve_status=None if overlap is None else overlap.solve_status_name,
        spin_increments=None if overlap is None else overlap.spin_increments,
    )


def _admissible_player_ids(turn: TurnInfo, *, perspective: int) -> tuple[int, ...]:
    player_ids: list[int] = []
    for score in turn.scores:
        skip = resolve_inference_admission_skip(
            turn,
            score.ownerid,
            perspective=perspective,
        )
        if skip is None:
            player_ids.append(score.ownerid)
    if not player_ids:
        raise RuntimeError("no admissible scores row for tier_solve probe")
    return tuple(player_ids)


def _load_turn(
    storage: StorageBackend,
    game_id: int,
    perspective: int,
    turn_number: int,
) -> TurnInfo:
    raw = require_dict(
        storage.get(TurnLoadService.turn_store_key(game_id, perspective, turn_number)),
        f"turn {turn_number} of game {game_id} perspective {perspective}",
    )
    settings_defaults = _settings_defaults(storage, game_id)
    return turn_info_from_json(raw, settings_defaults=settings_defaults)


def _settings_defaults(storage: StorageBackend, game_id: int) -> dict | None:
    try:
        info = storage.get(f"games/{game_id}/info")
    except NotFoundError:
        return None
    if not isinstance(info, dict):
        return None
    settings = info.get("settings")
    return settings if isinstance(settings, dict) else None
