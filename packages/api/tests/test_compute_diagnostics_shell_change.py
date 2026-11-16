"""A shell change reruns the freeze gate while freeze is armed for the game.

The operator shell is the last shell notified, process-wide. When it changes
under an armed game, work that left compute diagnostic scope is dispatched at
once instead of waiting for an unrelated dispatch pass. With freeze off, or
on the same shell, nothing is redispatched.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
)
from api.compute.diagnostics.controller import ComputeDiagnosticsController
from api.config import ApiConfig, set_config

GAME_ID = 628580
SHELL = ShellContextKey(game_id=GAME_ID, perspective=1, turn=6)
OTHER_PERSPECTIVE = ShellContextKey(game_id=GAME_ID, perspective=2, turn=6)
OTHER_GAME = ShellContextKey(game_id=GAME_ID + 1, perspective=1, turn=6)


@pytest.fixture(autouse=True)
def _diagnostics_enabled() -> Iterator[None]:
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


@pytest.fixture
def redispatched_games(monkeypatch) -> list[int]:
    """Record each game the controller redispatches after a gate change."""
    games: list[int] = []
    monkeypatch.setattr(
        ComputeDiagnosticsController,
        "_redispatch_after_gate_change",
        lambda _self, game_id: games.append(game_id),
    )
    return games


def test_a_shell_change_while_armed_redispatches_the_game_once(redispatched_games):
    controller = get_compute_diagnostics_controller()
    controller.set_freeze_armed(SHELL, freeze_armed=True)
    redispatched_games.clear()

    controller.on_shell_context(OTHER_PERSPECTIVE)

    assert redispatched_games == [GAME_ID]


def test_a_shell_change_with_freeze_off_does_not_redispatch(redispatched_games):
    controller = get_compute_diagnostics_controller()
    controller.on_shell_context(SHELL)

    controller.on_shell_context(OTHER_PERSPECTIVE)

    assert redispatched_games == []


def test_the_same_shell_does_not_redispatch(redispatched_games):
    controller = get_compute_diagnostics_controller()
    controller.set_freeze_armed(SHELL, freeze_armed=True)
    redispatched_games.clear()

    controller.on_shell_context(SHELL)

    assert redispatched_games == []


def test_a_game_change_with_start_frozen_runs_one_pass_for_the_new_game(redispatched_games):
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            compute_diagnostics=True,
            compute_diagnostics_start_frozen=True,
        )
    )
    controller = get_compute_diagnostics_controller()
    controller.on_shell_context(SHELL)
    redispatched_games.clear()

    controller.on_shell_context(OTHER_GAME)

    assert redispatched_games == [GAME_ID, GAME_ID + 1]


def test_arming_from_a_new_shell_while_already_armed_redispatches_once(redispatched_games):
    controller = get_compute_diagnostics_controller()
    controller.set_freeze_armed(SHELL, freeze_armed=True)
    redispatched_games.clear()

    controller.set_freeze_armed(OTHER_PERSPECTIVE, freeze_armed=True)

    assert redispatched_games == [GAME_ID]


def test_disarming_redispatches_the_game(redispatched_games):
    controller = get_compute_diagnostics_controller()
    controller.set_freeze_armed(SHELL, freeze_armed=True)
    redispatched_games.clear()

    controller.set_freeze_armed(SHELL, freeze_armed=False)

    assert redispatched_games == [GAME_ID]


def test_the_freeze_state_reports_whether_arming_changed_it():
    freeze_state = get_compute_diagnostics_controller()._freeze_state

    assert freeze_state.set_freeze_armed(GAME_ID, freeze_armed=True) is True
    assert freeze_state.set_freeze_armed(GAME_ID, freeze_armed=True) is False
    assert freeze_state.set_freeze_armed(GAME_ID, freeze_armed=False) is True
