"""Unit tests for MCP viewpoint eligibility refuse."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from api.models.game import GameInfo
from api.services.game_service import GameService
from mcp_adapter.eligibility import require_eligible_perspective
from mcp_adapter.errors import ViewpointEligibilityRefusedError


def test_require_eligible_perspective_returns_game_info(running_game_info: GameInfo):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info

    info = require_eligible_perspective(
        games,
        login_identity="arlowat",
        game_id=628580,
        perspective=2,
    )

    assert info is running_game_info


def test_require_eligible_perspective_refuses_other_slot(running_game_info: GameInfo):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info

    with pytest.raises(ViewpointEligibilityRefusedError) as exc:
        require_eligible_perspective(
            games,
            login_identity="arlowat",
            game_id=628580,
            perspective=1,
        )

    assert exc.value.perspective == 1
    assert exc.value.game_id == 628580
    assert exc.value.login_identity == "arlowat"
