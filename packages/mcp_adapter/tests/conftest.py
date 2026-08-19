"""Sample GameInfo for MCP adapter tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.models.enums import GameStatus
from api.models.game import GameInfo, TurnInfo
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json

_ASSETS_DIR = Path(__file__).resolve().parents[2] / "api" / "api" / "storage" / "assets"


@pytest.fixture
def sample_game_info() -> GameInfo:
    with open(_ASSETS_DIR / "game_info_sample.json") as f:
        return game_info_from_json(json.load(f))


@pytest.fixture
def running_game_info(sample_game_info: GameInfo) -> GameInfo:
    return replace(
        sample_game_info,
        game=replace(sample_game_info.game, status=GameStatus.RUNNING),
    )


@pytest.fixture
def sample_turn() -> TurnInfo:
    with open(_ASSETS_DIR / "turn_sample.json") as f:
        return turn_info_from_json(json.load(f))
