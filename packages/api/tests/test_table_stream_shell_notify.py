"""A table stream opening makes its shell the compute-diagnostics operator shell first.

``TurnAnalyticService`` notifies the diagnostics controller before a fleet or
scoreboard stream submits anything (for the scoreboard, before the prior-turn
fleet warm), so freeze already scopes to that shell when the stream's work is
dispatched. Table and map batches do not notify.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
)
from api.config import ApiConfig, set_config
from api.errors import NotFoundError
from api.services.stack import build_service_stack
from api.services.turn_analytic_service import TurnAnalyticService
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
GAME_ID = 628580
PERSPECTIVE = 1
TURN = 111
SHELL = ShellContextKey(game_id=GAME_ID, perspective=PERSPECTIVE, turn=TURN)


@pytest.fixture(autouse=True)
def _diagnostics_enabled() -> Iterator[None]:
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


@pytest.fixture
def analytics_service() -> TurnAnalyticService:
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put(f"games/{GAME_ID}/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put(f"games/{GAME_ID}/{PERSPECTIVE}/turns/{TURN}", json.load(f))
    _, _, _, _, analytics, _, _ = build_service_stack(backend)
    return analytics


def _operator_shell() -> ShellContextKey | None:
    return get_compute_diagnostics_controller()._active_shell_context()


def _record_operator_shell(calls: list[tuple[str, ShellContextKey | None]], name: str):
    def record(*_args, **_kwargs):
        calls.append((name, _operator_shell()))
        return iter(())

    return record


def test_a_fleet_stream_notifies_its_shell_before_it_submits(analytics_service, monkeypatch):
    calls: list[tuple[str, ShellContextKey | None]] = []
    monkeypatch.setattr(
        "api.analytics.fleet.iter_fleet_table_stream",
        _record_operator_shell(calls, "fleet stream"),
    )

    analytics_service.iter_fleet_table_stream(GAME_ID, PERSPECTIVE, TURN, (8,))

    assert calls == [("fleet stream", SHELL)]


def test_a_scoreboard_stream_notifies_its_shell_before_the_prior_turn_warm(
    analytics_service, monkeypatch
):
    calls: list[tuple[str, ShellContextKey | None]] = []
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_admission.is_build_inference_available",
        lambda _turn: True,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.prior_turn_fleet_torp_overlay"
        ".schedule_background_prior_turn_fleet_warm",
        _record_operator_shell(calls, "prior-turn warm"),
    )
    monkeypatch.setattr(
        "api.analytics.scores.iter_scores_table_inference_stream",
        _record_operator_shell(calls, "scoreboard stream"),
    )

    analytics_service.iter_scores_table_inference_stream(GAME_ID, PERSPECTIVE, TURN, (8,))

    assert calls == [("prior-turn warm", SHELL), ("scoreboard stream", SHELL)]


def test_a_table_batch_does_not_move_the_operator_shell(analytics_service):
    analytics_service.get_turn_analytics(GAME_ID, PERSPECTIVE, TURN, "scores")

    assert _operator_shell() is None


def test_a_stream_for_a_missing_turn_does_not_move_the_operator_shell(analytics_service):
    with pytest.raises(NotFoundError):
        analytics_service.iter_fleet_table_stream(GAME_ID, PERSPECTIVE, TURN + 50, (8,))

    assert _operator_shell() is None
