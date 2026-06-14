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


def _put_turn(storage, game_id: int, perspective: int, turn_number: int) -> None:
    with (ASSETS_DIR / "turn_sample.json").open(encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["settings"]["turn"] = turn_number
    payload["game"]["turn"] = turn_number
    storage.put(f"games/{game_id}/{perspective}/turns/{turn_number}", payload)


def test_prior_mining_accepts_missing_only_final_turn(tmp_path: Path) -> None:
    storage = configure_file_storage(storage_root=tmp_path)
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)

    with (ASSETS_DIR / "game_info_sample.json").open(encoding="utf-8") as handle:
        info_payload = json.load(handle)
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

    with (ASSETS_DIR / "game_info_sample.json").open(encoding="utf-8") as handle:
        info_payload = json.load(handle)
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
