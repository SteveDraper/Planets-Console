"""Tests for prior mining turn cache."""

from __future__ import annotations

from unittest.mock import MagicMock

from api.analytics.military_score_inference.prior_mining.turn_cache import MiningTurnCache
from api.models.game import TurnInfo


def test_mining_turn_cache_lists_stored_turns_once() -> None:
    turn_load = MagicMock()
    turn_load.list_stored_turn_numbers.return_value = [1, 2, 3]
    cache = MiningTurnCache(turn_load)

    assert cache.stored_turn_numbers(628580, 1) == frozenset({1, 2, 3})
    assert 2 in cache.stored_turn_numbers(628580, 1)
    turn_load.list_stored_turn_numbers.assert_called_once_with(628580, 1)


def test_mining_turn_cache_reuses_turn_info() -> None:
    turn_load = MagicMock()
    turn = MagicMock(spec=TurnInfo)
    turn_load.get_turn_info.return_value = turn
    cache = MiningTurnCache(turn_load)

    assert cache.get_turn_info(628580, 1, 5) is turn
    assert cache.get_turn_info(628580, 1, 5) is turn
    turn_load.get_turn_info.assert_called_once_with(628580, 1, 5)
