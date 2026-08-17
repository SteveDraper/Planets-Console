"""Viewpoint eligibility: allowed perspective set from GameInfo + login identity."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.errors import ValidationError
from api.models.enums import GameStatus
from api.models.game import GameInfo
from api.serialization.game import game_info_from_json
from api.services.viewpoint_eligibility import ViewpointEligibilityService

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_game_info():
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        return game_info_from_json(json.load(f))


def _with_status(info: GameInfo, status: GameStatus) -> GameInfo:
    return replace(info, game=replace(info.game, status=status))


class TestEligiblePerspectives:
    def test_empty_login_is_not_a_core_input(self, sample_game_info):
        with pytest.raises(ValidationError, match="login identity"):
            ViewpointEligibilityService.eligible_perspectives(sample_game_info, "")

    def test_whitespace_login_is_not_a_core_input(self, sample_game_info):
        with pytest.raises(ValidationError, match="login identity"):
            ViewpointEligibilityService.eligible_perspectives(sample_game_info, "   ")

    def test_in_progress_player_own_slot_only(self, sample_game_info):
        info = _with_status(sample_game_info, GameStatus.RUNNING)
        assert ViewpointEligibilityService.eligible_perspectives(info, "arlowat") == frozenset({2})

    def test_in_progress_player_match_is_case_insensitive(self, sample_game_info):
        info = _with_status(sample_game_info, GameStatus.RUNNING)
        assert ViewpointEligibilityService.eligible_perspectives(info, "ArloWat") == frozenset({2})

    def test_in_progress_non_player_spectator_only(self, sample_game_info):
        info = _with_status(sample_game_info, GameStatus.RUNNING)
        assert ViewpointEligibilityService.eligible_perspectives(info, "nobody") == frozenset(
            {ViewpointEligibilityService.SPECTATOR_PERSPECTIVE}
        )

    def test_finished_all_player_slots_no_spectator(self, sample_game_info):
        assert sample_game_info.game.status == GameStatus.FINISHED
        allowed = ViewpointEligibilityService.eligible_perspectives(sample_game_info, "nobody")
        assert allowed == frozenset({1, 2, 3})
        assert ViewpointEligibilityService.SPECTATOR_PERSPECTIVE not in allowed

    def test_finished_player_login_still_all_slots(self, sample_game_info):
        allowed = ViewpointEligibilityService.eligible_perspectives(sample_game_info, "arlowat")
        assert allowed == frozenset({1, 2, 3})
