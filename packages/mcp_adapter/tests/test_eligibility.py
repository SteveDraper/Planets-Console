"""Unit tests for MCP viewpoint eligibility refuse."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from api.models.game import GameInfo
from api.services.game_service import GameService
from mcp_adapter.eligibility import (
    eligible_perspectives_for_login,
    require_eligible_perspective,
)
from mcp_adapter.errors import ViewpointEligibilityRefusedError

_GAME_ID = 628580
_LOGIN = "arlowat"
_OWN_SLOT = 2


def _game_service(info: GameInfo) -> MagicMock:
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = info
    return games


def test_require_eligible_perspective_returns_game_info(running_game_info: GameInfo):
    games = _game_service(running_game_info)

    info = require_eligible_perspective(
        games,
        login_identity=_LOGIN,
        game_id=_GAME_ID,
        perspective=_OWN_SLOT,
    )

    assert info is running_game_info
    games.get_game_info.assert_called_once_with(_GAME_ID)


def test_require_eligible_perspective_refuses_other_slot(running_game_info: GameInfo):
    games = _game_service(running_game_info)

    with pytest.raises(ViewpointEligibilityRefusedError) as exc:
        require_eligible_perspective(
            games,
            login_identity=_LOGIN,
            game_id=_GAME_ID,
            perspective=1,
        )

    assert exc.value.perspective == 1
    assert exc.value.game_id == _GAME_ID
    assert exc.value.login_identity == _LOGIN
    games.get_game_info.assert_called_once_with(_GAME_ID)


def test_eligible_perspectives_for_login_returns_core_allowed_set(
    running_game_info: GameInfo,
):
    games = _game_service(running_game_info)

    allowed = eligible_perspectives_for_login(
        games,
        login_identity=_LOGIN,
        game_id=_GAME_ID,
    )

    assert allowed == frozenset({_OWN_SLOT})
    games.get_game_info.assert_called_once_with(_GAME_ID)


def test_require_eligible_perspective_uses_one_core_eligibility_call(
    running_game_info: GameInfo,
):
    games = _game_service(running_game_info)
    core_allowed = frozenset({_OWN_SLOT})

    with patch(
        "mcp_adapter.eligibility.ViewpointEligibilityService.eligible_perspectives",
        return_value=core_allowed,
    ) as predicate:
        info = require_eligible_perspective(
            games,
            login_identity=_LOGIN,
            game_id=_GAME_ID,
            perspective=_OWN_SLOT,
        )

    assert info is running_game_info
    games.get_game_info.assert_called_once_with(_GAME_ID)
    predicate.assert_called_once_with(running_game_info, _LOGIN)


def test_eligible_perspectives_for_login_uses_one_core_eligibility_call(
    running_game_info: GameInfo,
):
    games = _game_service(running_game_info)
    core_allowed = frozenset({7, 9})

    with patch(
        "mcp_adapter.eligibility.ViewpointEligibilityService.eligible_perspectives",
        return_value=core_allowed,
    ) as predicate:
        allowed = eligible_perspectives_for_login(
            games,
            login_identity=_LOGIN,
            game_id=_GAME_ID,
        )

    assert allowed is core_allowed
    games.get_game_info.assert_called_once_with(_GAME_ID)
    predicate.assert_called_once_with(running_game_info, _LOGIN)
