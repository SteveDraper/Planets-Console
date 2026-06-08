"""Tests for load-all completeness status."""

import json
from unittest.mock import MagicMock

import pytest
from api.errors import LoginCredentialsRequiredError, ValidationError
from api.transport.game_info_update import RefreshGameInfoParams
from conftest import (
    ASSETS_DIR,
    archive_turn_rst,
    final_load_all_result,
    load_services,
    mock_planets_load_game_info,
    put_minimal_turn,
)


def test_load_all_turns_status_complete_when_all_turns_present() -> None:
    storage, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    for perspective in range(1, len(info_payload["players"]) + 1):
        for turn_number in range(1, latest + 1):
            put_minimal_turn(storage, 628580, perspective, turn_number)

    status = load_all.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is True
    assert status.is_game_finished is True
    assert status.latest_turn == latest


def test_load_all_turns_status_incomplete_when_turn_missing() -> None:
    storage, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    storage.put(
        "games/628580/1/turns/1",
        {"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
    )

    status = load_all.load_all_turns_status_for_user(628580, "player")
    assert status.complete is False


def test_load_all_turns_status_raises_when_login_missing_for_in_progress() -> None:
    """In-progress status uses the same login requirement as bulk load."""
    storage, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["status"] = 1
    storage.put("games/628580/info", info_payload)
    assert info_payload["game"]["turn"] >= 1

    with pytest.raises(LoginCredentialsRequiredError):
        load_all.load_all_turns_status_for_user(628580, "")


def test_load_all_turns_status_raises_when_username_not_in_game() -> None:
    """In-progress status must not swallow unknown-player errors."""
    storage, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["status"] = 1
    storage.put("games/628580/info", info_payload)

    with pytest.raises(ValidationError, match="not a player"):
        load_all.load_all_turns_status_for_user(628580, "not-a-player")


def test_load_all_turns_status_expected_perspectives_match_load_for_in_progress() -> None:
    storage, credentials, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["status"] = 1
    info_payload["game"]["turn"] = 2
    info_payload["settings"]["turn"] = 2
    info_payload["players"] = info_payload["players"][:1]
    info_payload["players"][0]["username"] = "captain"
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    status = load_all.load_all_turns_status_for_user(628580, "captain")
    assert status.expected_perspectives == [1]
    assert status.is_game_finished is False

    planets = MagicMock()
    mock_planets_load_game_info(planets, info_payload)

    def load_turn_side_effect(**kwargs):
        turn_number = kwargs.get("turn")
        return {"success": True, "rst": archive_turn_rst(628580, turn_number)}

    planets.load_turn.side_effect = load_turn_side_effect
    result = final_load_all_result(
        load_all,
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )
    assert result.perspectives_touched == [1]


def test_load_all_turns_status_complete_when_latest_turn_zero() -> None:
    storage, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 0
    storage.put("games/628580/info", info_payload)

    status = load_all.load_all_turns_status_for_user(628580, "")
    assert status.latest_turn == 0
    assert status.complete is True


def test_load_all_turns_status_complete_eliminated_through_statusturn_only() -> None:
    """628580 perspective 1 eliminated at turn 49; post-death turns are not required."""
    storage, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    player_count = len(info_payload["players"])
    assert info_payload["players"][0]["status"] == 3
    assert info_payload["players"][0]["statusturn"] == 49

    for turn_number in range(1, 50):
        put_minimal_turn(storage, 628580, 1, turn_number)
    for perspective in range(2, player_count + 1):
        for turn_number in range(1, latest + 1):
            put_minimal_turn(storage, 628580, perspective, turn_number)

    status = load_all.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is True
    assert status.latest_turn == latest


def test_load_all_turns_status_incomplete_eliminated_missing_statusturn() -> None:
    storage, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    player_count = len(info_payload["players"])

    for turn_number in range(1, 49):
        put_minimal_turn(storage, 628580, 1, turn_number)
    for perspective in range(2, player_count + 1):
        for turn_number in range(1, latest + 1):
            put_minimal_turn(storage, 628580, perspective, turn_number)

    status = load_all.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is False


def test_load_all_turns_status_incomplete_eliminated_post_death_without_statusturn() -> None:
    """Post-death turns alone do not satisfy completeness for an eliminated slot."""
    storage, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    player_count = len(info_payload["players"])

    for turn_number in range(50, latest + 1):
        put_minimal_turn(storage, 628580, 1, turn_number)
    for perspective in range(2, player_count + 1):
        for turn_number in range(1, latest + 1):
            put_minimal_turn(storage, 628580, perspective, turn_number)

    status = load_all.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is False
