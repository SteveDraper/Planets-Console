"""Tests for scores inference row persistence and invalidation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    get_inference_row_scheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    iter_scores_table_inference_events,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reschedule_inference_row,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    return backend


@pytest.fixture
def persistence(memory_backend):
    return InferenceRowPersistenceService(memory_backend)


def test_persistence_row_round_trip(persistence):
    row = PersistedInferenceRow(
        status=STATUS_EXACT,
        summary="cached",
        solution_count=1,
        is_complete=True,
        solutions=[{"objectiveValue": 1.0, "actions": [], "shipBuilds": []}],
        diagnostics={"playerId": 8},
    )
    persistence.put_row(628580, 1, 111, 8, row)
    loaded = persistence.get_row(628580, 1, 111, 8)
    assert loaded == row


def test_invalidate_for_turn_write_deletes_pair_documents(memory_backend, persistence):
    persistence.put_row(
        628580,
        1,
        110,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="t110",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="t111",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    cleared = persistence.invalidate_for_turn_write(628580, 1, 111)
    assert cleared == {111, 110}
    assert persistence.get_row(628580, 1, 111, 8) is None
    assert persistence.get_row(628580, 1, 110, 8) is None


def test_stream_replays_persisted_row_without_scheduler_work(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()
    player_id = sample_turn.scores[0].ownerid
    persistence.put_row(
        628580,
        1,
        sample_turn.settings.turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="from cache",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    scheduler = get_inference_row_scheduler()
    stream = iter_scores_table_inference_events(
        sample_turn,
        (player_id,),
        game_id=628580,
        perspective=1,
        persistence=persistence,
    )
    events = [next(stream), next(stream)]
    stream.close()
    assert events[0] == {"type": "globalPause", "paused": False}
    assert events[1]["type"] == "complete"
    assert events[1]["playerId"] == player_id
    assert events[1]["summary"] == "from cache"
    assert len(scheduler._runs) == 0


def test_mask_change_deletes_persisted_row(memory_backend):
    persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(persistence)
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="before mask",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    invalidation.on_hull_mask_changed(628580, 1, 111, 8)
    assert persistence.get_row(628580, 1, 111, 8) is None


def test_recompute_clears_host_turn_document(memory_backend):
    _, _, _, _, analytics = build_service_stack(memory_backend)
    persistence = InferenceRowPersistenceService(memory_backend)
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    analytics.recompute_scores_inference(628580, 1, 111)
    assert persistence.get_row(628580, 1, 111, 8) is None


def test_turn_store_invalidates_inference_persistence(memory_backend):
    _, turns, _, _, _ = build_service_stack(memory_backend)
    persistence = InferenceRowPersistenceService(memory_backend)
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    with open(ASSETS_DIR / "turn_sample.json") as f:
        turns._store_turn_rst(628580, 1, 111, json.load(f))
    assert persistence.get_row(628580, 1, 111, 8) is None


def test_reschedule_without_active_stream_is_noop():
    reset_inference_table_stream_registry_for_tests()
    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=111)
    assert reschedule_inference_row(scope, 8) is False
