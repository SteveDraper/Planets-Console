"""Tests for finished-game load-all completeness helpers."""

from __future__ import annotations

import json
from pathlib import Path

from api.services.load_all_completeness import (
    blocking_finished_game_load_all_gaps,
    is_finished_game_load_all_complete,
    is_finished_game_load_all_complete_for_prior_mining,
)

from tests.inference_corpus.storage_loader import (
    configure_file_storage,
    make_game_service,
    make_turn_load_service,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
_MINIMAL_GAME_ID = 900_001
_MINIMAL_LATEST_TURN = 5
_MINIMAL_PLAYER_COUNT = 2


def _minimal_game_info_payload() -> dict:
    with (ASSETS_DIR / "game_info_sample.json").open(encoding="utf-8") as handle:
        payload = json.load(handle)
    active_players = [player for player in payload["players"] if player["status"] == 1][
        :_MINIMAL_PLAYER_COUNT
    ]
    for index, player in enumerate(active_players, start=1):
        player["id"] = index
    payload["game"]["id"] = _MINIMAL_GAME_ID
    payload["game"]["turn"] = _MINIMAL_LATEST_TURN
    payload["players"] = active_players
    return payload


def _minimal_turn_payload(turn_number: int) -> dict:
    return {"settings": {"turn": turn_number}, "game": {"turn": turn_number}}


def _put_turn(storage, game_id: int, perspective: int, turn_number: int) -> None:
    storage.put(
        f"games/{game_id}/{perspective}/turns/{turn_number}",
        _minimal_turn_payload(turn_number),
    )


def test_prior_mining_accepts_missing_only_final_turn(tmp_path: Path) -> None:
    storage = configure_file_storage(storage_root=tmp_path)
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)

    info_payload = _minimal_game_info_payload()
    latest_turn = info_payload["game"]["turn"]
    player_count = len(info_payload["players"])
    game_id = info_payload["game"]["id"]
    storage.put(f"games/{game_id}/info", info_payload)

    for perspective in range(1, player_count + 1):
        for turn_number in range(1, latest_turn):
            _put_turn(storage, game_id, perspective, turn_number)

    info = game_service.get_game_info(game_id)
    assert not is_finished_game_load_all_complete(info, turn_load, game_id)
    assert is_finished_game_load_all_complete_for_prior_mining(info, turn_load, game_id)
    assert blocking_finished_game_load_all_gaps(info, turn_load, game_id) == ()


def test_prior_mining_rejects_missing_non_final_turn(tmp_path: Path) -> None:
    storage = configure_file_storage(storage_root=tmp_path)
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)

    info_payload = _minimal_game_info_payload()
    latest_turn = info_payload["game"]["turn"]
    player_count = len(info_payload["players"])
    game_id = info_payload["game"]["id"]
    storage.put(f"games/{game_id}/info", info_payload)

    for perspective in range(1, player_count + 1):
        for turn_number in range(1, latest_turn - 1):
            _put_turn(storage, game_id, perspective, turn_number)

    info = game_service.get_game_info(game_id)
    assert not is_finished_game_load_all_complete_for_prior_mining(info, turn_load, game_id)
    blocking = blocking_finished_game_load_all_gaps(info, turn_load, game_id)
    assert blocking
    assert latest_turn - 1 in blocking[0].missing_turns
