"""Scores ``tier_solve`` occupancy probe against a seeded store."""

from __future__ import annotations

import json

from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.analytics.scores.tier_solve_jobs import time_scores_tier_solve_jobs
from api.storage.memory_asset import MemoryAssetBackend

from tests.inference_corpus.manifest import FIXTURES_ROOT

CORPUS_GAME_ID = 628580
CORPUS_PERSPECTIVE = 1
CORPUS_TURN = 3
CORPUS_PLAYER_ID = 1


def _seed_corpus_backend() -> MemoryAssetBackend:
    info = json.loads((FIXTURES_ROOT / "628580" / "info.json").read_text(encoding="utf-8"))
    turn = json.loads(
        (FIXTURES_ROOT / "628580" / "1" / "turns" / "3.json").read_text(encoding="utf-8")
    )
    backend = MemoryAssetBackend(initial={})
    backend.put("games/628580/info", info)
    backend.put("games/628580/1/turns/3", turn)
    return backend


def test_time_scores_tier_solve_jobs_runs_registered_tier_on_corpus():
    reset_tier_row_run_registry_for_tests()
    storage = _seed_corpus_backend()

    timing = time_scores_tier_solve_jobs(
        storage,
        game_id=CORPUS_GAME_ID,
        perspective=CORPUS_PERSPECTIVE,
        turn_number=CORPUS_TURN,
        player_id=CORPUS_PLAYER_ID,
    )

    payload = timing.to_probe_json()
    assert payload["gameId"] == CORPUS_GAME_ID
    assert payload["perspective"] == CORPUS_PERSPECTIVE
    assert payload["turn"] == CORPUS_TURN
    assert payload["playerId"] == CORPUS_PLAYER_ID
    assert payload["tierWallSeconds"] > 0.0
    assert payload["stepOutcome"] in ("continue", "persist", "complete", "park")
    assert payload["solveInvoked"] in (True, False)
    assert payload["solveCount"] >= 0
    if payload["solveInvoked"]:
        assert payload["solveCount"] >= 1
        assert payload["solveWallSeconds"] > 0.0
        assert isinstance(payload["pythonProgressedDuringSolve"], bool)
        assert payload["overlapFraction"] is not None
        assert payload["solveStatus"]
        assert payload["spinIncrements"] is not None
    else:
        assert payload["pythonProgressedDuringSolve"] is None
        assert payload["solveWallSeconds"] is None
