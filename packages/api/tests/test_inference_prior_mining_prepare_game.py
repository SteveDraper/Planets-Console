"""Tests for prior mining game preparation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.analytics.military_score_inference.prior_mining.prepare_game import (
    PrepareGameResult,
    prepare_game_for_mining,
)
from api.errors import ValidationError


def test_prepare_game_for_mining_returns_error_result_instead_of_raising():
    storage = MagicMock()
    turn_load = MagicMock()
    game_service = MagicMock()
    planets = MagicMock()

    with (
        patch(
            "api.analytics.military_score_inference.prior_mining.prepare_game.ensure_game_info_stored",
            return_value=MagicMock(),
        ),
        patch(
            "api.analytics.military_score_inference.prior_mining.prepare_game.GameService.is_game_finished",
            return_value=True,
        ),
        patch(
            "api.analytics.military_score_inference.prior_mining.prepare_game.import_finished_game_loadall_if_needed",
            side_effect=ValidationError("invalid archive turn"),
        ),
    ):
        result = prepare_game_for_mining(
            game_id=656637,
            storage=storage,
            turn_load=turn_load,
            game_service=game_service,
            planets=planets,
        )

    assert result == PrepareGameResult(
        game_id=656637,
        outcome="error",
        error_message="invalid archive turn",
    )
