"""``POST /v1/games/{game_id}/backfill-walks/stop``: 204 for any game, drain after the response."""

from __future__ import annotations

import asyncio

import pytest
from api.compute.in_flight_settle import GameWork, InFlightSettlePolicy, InFlightWork
from api.compute.runtime import peek_compute_orchestrator, reset_orchestrators_for_tests
from api.config import ApiConfig, set_config
from api.routers.games import post_backfill_walks_stop
from api.services.backfill_walk_stop import WalkStopPolicy
from api.services.in_flight_orchestrator import process_in_flight_orchestrator
from api.storage_factory import clear_backend_cache
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient


class _RecordingOrchestrator:
    """Records the stop's settle and the drain, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, InFlightWork | None]] = []

    def settle_in_flight_work(self, work: InFlightWork, policy: InFlightSettlePolicy) -> None:
        assert isinstance(policy, WalkStopPolicy)
        self.calls.append(("settle", work))

    def drain_post_lock_callbacks(self) -> None:
        self.calls.append(("drain", None))


@pytest.fixture(autouse=True)
def _empty_storage():
    clear_backend_cache()
    set_config(
        ApiConfig(storage_backend="ephemeral", storage_asset_path=None, include_dummy_data=False)
    )
    yield
    clear_backend_cache()


@pytest.fixture
def orchestrator():
    from api.app import app

    recording = _RecordingOrchestrator()
    app.dependency_overrides[process_in_flight_orchestrator] = lambda: recording
    yield recording
    app.dependency_overrides.pop(process_in_flight_orchestrator, None)


@pytest.mark.parametrize("game_id", [628580, 999999])
def test_the_stop_returns_204_for_any_game_and_settles_that_game(orchestrator, game_id):
    from api.app import app

    response = TestClient(app).post(f"/v1/games/{game_id}/backfill-walks/stop")

    assert response.status_code == 204
    assert response.content == b""
    assert orchestrator.calls[0][0] == "settle"
    work = orchestrator.calls[0][1]
    assert isinstance(work, GameWork)
    assert work.game_id == game_id
    assert orchestrator.calls[1:] == [("drain", None)]


def test_the_drain_runs_in_the_responses_background_task():
    recording = _RecordingOrchestrator()
    background = BackgroundTasks()

    response = post_backfill_walks_stop(628580, background, orchestrator=recording)

    assert response.status_code == 204
    assert [call for call, _work in recording.calls] == ["settle"]
    assert [task.func for task in background.tasks] == [recording.drain_post_lock_callbacks]
    asyncio.run(background())
    assert [call for call, _work in recording.calls] == ["settle", "drain"]


def test_the_stop_without_a_process_orchestrator_is_a_no_op():
    from api.app import app

    reset_orchestrators_for_tests()
    response = TestClient(app).post("/v1/games/1/backfill-walks/stop")

    assert response.status_code == 204
    assert peek_compute_orchestrator() is None
