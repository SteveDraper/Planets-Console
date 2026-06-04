"""Tests for inference corpus case discovery from storage."""

import json

import pytest
from api.services.store_service import StoreService
from api.storage.file import FileStorageBackend

from tests.inference_corpus.discovery import (
    discover_cases,
    discover_cases_for_game,
    list_perspectives_with_turn_pair,
)
from tests.inference_corpus.manifest import FIXTURES_ROOT


@pytest.fixture
def discovery_storage(tmp_path):
    backend = FileStorageBackend(tmp_path / "data")
    fixture_game_root = FIXTURES_ROOT / "628580"
    info_src = fixture_game_root / "info.json"
    backend.put("games/628580/info", json.loads(info_src.read_text()))
    for perspective in (1, 2):
        for turn_number in (2, 3):
            turn_src = fixture_game_root / str(perspective) / "turns" / f"{turn_number}.json"
            if turn_src.is_file():
                backend.put(
                    f"games/628580/{perspective}/turns/{turn_number}",
                    json.loads(turn_src.read_text()),
                )
    return StoreService(backend)


def test_discover_cases_for_game_finds_consecutive_pairs(discovery_storage):
    cases = discover_cases_for_game(discovery_storage, 628580)
    assert [case.id for case in cases] == ["628580-p1-host2"]
    assert cases[0].host_turn == 2
    assert cases[0].perspective == 1


def test_discover_cases_skips_non_consecutive_turn_gaps(tmp_path):
    backend = FileStorageBackend(tmp_path / "data")
    backend.put("games/99/info", {"settings": {}, "players": [{"id": 1}]})
    backend.put("games/99/1/turns/2", {"settings": {"turn": 2}})
    backend.put("games/99/1/turns/4", {"settings": {"turn": 4}})
    store = StoreService(backend)

    assert discover_cases_for_game(store, 99) == []


def test_discover_cases_all_games(discovery_storage):
    cases = discover_cases(discovery_storage)
    assert len(cases) == 1
    assert cases[0].game_id == 628580


def test_list_perspectives_with_turn_pair(discovery_storage):
    perspectives = list_perspectives_with_turn_pair(
        discovery_storage,
        game_id=628580,
        host_turn=2,
        score_turn=3,
    )
    assert perspectives == [1]


def test_discover_cases_ignores_non_numeric_perspective_segments(discovery_storage):
    """Non-numeric game child segments are ignored; only perspective 1 has turn pairs."""
    cases = discover_cases_for_game(discovery_storage, 628580)
    assert all(case.perspective == 1 for case in cases)
