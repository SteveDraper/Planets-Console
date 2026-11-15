"""BFF ``POST /games/{game_id}/backfill-walks/stop``: 204 for any game, then the follow-up."""

from __future__ import annotations

import asyncio

import pytest
from api.compute.runtime import (
    get_compute_orchestrator,
    peek_compute_orchestrator,
    reset_orchestrators_for_tests,
)
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.services.backfill_walk_stop import WalkStopFollowUp
from api.storage_factory import clear_backend_cache
from bff.app import app
from bff.config import BffConfig
from bff.config import set_config as set_bff_config
from bff.core_client import clear_core_client_cache, get_core_client
from bff.routers.games import post_backfill_walks_stop
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

_STOP_PATH = "/games/{game_id}/backfill-walks/stop"


class _RecordingCore:
    """Records the stop, and the run of the follow-up the stop returns."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def stop_backfill_walks(self, game_id: int) -> WalkStopFollowUp:
        self.calls.append(("stop", game_id))
        return lambda: self.calls.append(("follow_up", game_id))


@pytest.fixture(autouse=True)
def _reset():
    clear_backend_cache()
    clear_core_client_cache()
    set_bff_config(BffConfig())
    set_api_config(
        ApiConfig(storage_backend="ephemeral", storage_asset_path=None, include_dummy_data=False)
    )
    yield
    reset_orchestrators_for_tests()
    clear_core_client_cache()
    clear_backend_cache()


@pytest.fixture
def core() -> _RecordingCore:
    recording = _RecordingCore()
    app.dependency_overrides[get_core_client] = lambda: recording
    yield recording
    app.dependency_overrides.pop(get_core_client, None)


@pytest.mark.parametrize("game_id", [628580, 999999])
def test_the_stop_returns_204_for_any_game_then_runs_its_follow_up(core, game_id):
    response = TestClient(app).post(_STOP_PATH.format(game_id=game_id))

    assert response.status_code == 204
    assert response.content == b""
    assert core.calls == [("stop", game_id), ("follow_up", game_id)]


def test_the_follow_up_runs_in_the_responses_background_task():
    recording = _RecordingCore()
    background = BackgroundTasks()

    response = post_backfill_walks_stop(628580, background, core=recording)

    assert response.status_code == 204
    assert recording.calls == [("stop", 628580)]
    assert len(background.tasks) == 1
    asyncio.run(background())
    assert recording.calls == [("stop", 628580), ("follow_up", 628580)]


def test_the_core_client_stop_returns_a_follow_up_that_drains_the_process_orchestrator(
    monkeypatch,
):
    """The BFF schedules the follow-up Core's stop hands back; it never names the compute drain."""
    orchestrator = get_compute_orchestrator()
    drains: list[str] = []
    monkeypatch.setattr(orchestrator, "drain_post_lock_callbacks", lambda: drains.append("drained"))

    follow_up = get_core_client().stop_backfill_walks(628580)
    assert drains == []
    follow_up()

    assert drains == ["drained"]


def test_the_stop_reaches_core_without_creating_an_orchestrator():
    reset_orchestrators_for_tests()

    response = TestClient(app).post(_STOP_PATH.format(game_id=1))

    assert response.status_code == 204
    assert peek_compute_orchestrator() is None


def test_the_stop_is_in_the_bff_schema():
    assert "post" in app.openapi()["paths"][_STOP_PATH]
