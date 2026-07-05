"""Regression tests: table-stream scope teardown on all connect exit paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.fleet_table_stream_rows import iter_fleet_table_stream_events
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    iter_scores_table_inference_events,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.streaming.table_stream.connect import (
    AdmissionDispatch,
    iter_table_stream_connect_with_scope,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def persistence(memory_backend):
    from api.analytics.fleet.persistence import FleetSnapshotPersistenceService

    return FleetSnapshotPersistenceService(memory_backend)


@pytest.fixture
def memory_backend():
    from api.storage.memory_asset import MemoryAssetBackend

    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        backend.put("games/628580/1/turns/111", json.load(handle))
    return backend


def _install_scores_scheduler(monkeypatch: pytest.MonkeyPatch) -> InferenceRowScheduler:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)

    def _get_scheduler() -> InferenceRowScheduler:
        return scheduler

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_scheduler.get_inference_row_scheduler",
        _get_scheduler,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_rows.get_inference_row_scheduler",
        _get_scheduler,
    )
    return scheduler


def _install_fleet_scheduler(monkeypatch: pytest.MonkeyPatch) -> FleetTableStreamScheduler:
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)

    def _get_scheduler() -> FleetTableStreamScheduler:
        return scheduler

    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_rows.get_fleet_table_stream_scheduler",
        _get_scheduler,
    )
    return scheduler


def test_scores_empty_player_ids_releases_scope_for_reconnect(sample_turn, monkeypatch):
    scheduler = _install_scores_scheduler(monkeypatch)

    first = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        scheduler=scheduler,
    )
    assert next(first) == {"type": "globalPause", "paused": False}
    first.close()

    assert not scheduler._scope_guard.has_active_table_stream

    second = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        scheduler=scheduler,
    )
    try:
        event = next(second)
        assert event == {"type": "globalPause", "paused": False}
    finally:
        second.close()


def test_scores_schedule_failed_releases_scope_for_reconnect(sample_turn, monkeypatch):
    scheduler = _install_scores_scheduler(monkeypatch)
    player_id = sample_turn.scores[0].ownerid

    def _failing_dispatch(
        self: InferenceTableStreamController,
        player_id: int,
        admission: object,
    ) -> AdmissionDispatch:
        return AdmissionDispatch(schedule_failed=True)

    monkeypatch.setattr(
        InferenceTableStreamController,
        "dispatch_admission",
        _failing_dispatch,
    )

    stream = iter_scores_table_inference_events(
        sample_turn,
        (player_id,),
        game_id=628580,
        perspective=1,
        scheduler=scheduler,
    )
    events = list(stream)
    assert events[0] == {"type": "globalPause", "paused": False}
    assert not scheduler._scope_guard.has_active_table_stream

    replacement = iter_scores_table_inference_events(
        sample_turn,
        (player_id,),
        game_id=628580,
        perspective=1,
        scheduler=scheduler,
    )
    try:
        next(replacement)
    finally:
        replacement.close()


def test_scores_lost_ownership_mid_connect_releases_scope_for_reconnect(
    sample_turn,
    monkeypatch,
):
    scheduler = _install_scores_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:3])
    admission_calls = 0
    original_resolve = InferenceTableStreamController.resolve_row_admission
    preempting_stream = None

    def _resolve_then_preempt(
        self: InferenceTableStreamController,
        player_id: int,
        *,
        force_schedule: bool = False,
    ):
        nonlocal admission_calls, preempting_stream
        admission_calls += 1
        if admission_calls == 2:
            preempting_stream = iter_scores_table_inference_events(
                sample_turn,
                (),
                game_id=628580,
                perspective=1,
                scheduler=scheduler,
            )
            next(preempting_stream)
        return original_resolve(self, player_id, force_schedule=force_schedule)

    monkeypatch.setattr(
        InferenceTableStreamController,
        "resolve_row_admission",
        _resolve_then_preempt,
    )

    stream = iter_scores_table_inference_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        scheduler=scheduler,
    )
    list(stream)

    assert preempting_stream is not None
    preempting_stream.close()

    assert not scheduler._scope_guard.has_active_table_stream

    replacement = iter_scores_table_inference_events(
        sample_turn,
        (player_ids[0],),
        game_id=628580,
        perspective=1,
        scheduler=scheduler,
    )
    try:
        next(replacement)
    finally:
        replacement.close()


def test_fleet_empty_player_ids_releases_scope_for_reconnect(
    sample_turn,
    monkeypatch,
    persistence,
):
    scheduler = _install_fleet_scheduler(monkeypatch)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )

    first = iter_fleet_table_stream_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=persistence,
        scheduler=scheduler,
    )
    first.close()

    assert not scheduler._scope_guard.has_active_table_stream

    second = iter_fleet_table_stream_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=persistence,
        scheduler=scheduler,
    )
    try:
        events = list(second)
        assert events == []
    finally:
        second.close()


def test_fleet_schedule_failed_releases_scope_for_reconnect(
    sample_turn,
    monkeypatch,
    persistence,
):
    from api.analytics.fleet.fleet_table_stream_controller import FleetTableStreamController

    scheduler = _install_fleet_scheduler(monkeypatch)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    player_id = sample_turn.scores[0].ownerid

    def _failing_dispatch(
        self: FleetTableStreamController,
        player_id: int,
        admission: object,
    ) -> AdmissionDispatch:
        return AdmissionDispatch(schedule_failed=True)

    monkeypatch.setattr(
        FleetTableStreamController,
        "dispatch_admission",
        _failing_dispatch,
    )

    stream = iter_fleet_table_stream_events(
        sample_turn,
        (player_id,),
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=persistence,
        scheduler=scheduler,
    )
    list(stream)
    assert not scheduler._scope_guard.has_active_table_stream

    replacement = iter_fleet_table_stream_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=persistence,
        scheduler=scheduler,
    )
    try:
        list(replacement)
    finally:
        replacement.close()


def test_fleet_lost_ownership_mid_connect_releases_scope_for_reconnect(
    sample_turn,
    monkeypatch,
    persistence,
):
    from api.analytics.fleet.fleet_table_stream_rows import resolve_player_stream_admission

    scheduler = _install_fleet_scheduler(monkeypatch)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:3])
    admission_calls = 0
    preempting_stream = None
    original_resolve = resolve_player_stream_admission

    def _resolve_then_preempt(*args, **kwargs):
        nonlocal admission_calls, preempting_stream
        admission_calls += 1
        if admission_calls == 2:
            preempting_stream = iter_fleet_table_stream_events(
                sample_turn,
                (),
                game_id=628580,
                perspective=1,
                fleet_services=services,
                persistence=persistence,
                scheduler=scheduler,
            )
            list(preempting_stream)
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_rows.resolve_player_stream_admission",
        _resolve_then_preempt,
    )

    stream = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=persistence,
        scheduler=scheduler,
    )
    list(stream)

    assert preempting_stream is not None
    preempting_stream.close()

    assert not scheduler._scope_guard.has_active_table_stream

    replacement = iter_fleet_table_stream_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=persistence,
        scheduler=scheduler,
    )
    try:
        list(replacement)
    finally:
        replacement.close()


def test_scores_policy_factory_failure_releases_scope_for_reconnect(sample_turn, monkeypatch):
    scheduler = _install_scores_scheduler(monkeypatch)
    stream_scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=111)

    def _failing_policy_factory(_stream_token: str):
        raise RuntimeError("policy construction failed")

    stream = iter_table_stream_connect_with_scope(
        begin_scope=lambda: scheduler.begin_scope(stream_scope),
        end_scope=lambda stream_token: scheduler.end_inference_stream(
            stream_scope,
            (),
            stream_token=stream_token,
        ),
        policy_factory=_failing_policy_factory,
        player_ids=(),
    )
    with pytest.raises(RuntimeError, match="policy construction failed"):
        next(stream)

    assert not scheduler._scope_guard.has_active_table_stream

    replacement = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        scheduler=scheduler,
    )
    try:
        assert next(replacement) == {"type": "globalPause", "paused": False}
    finally:
        replacement.close()


def test_fleet_policy_factory_failure_releases_scope_for_reconnect(
    sample_turn,
    monkeypatch,
    persistence,
):
    from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope

    scheduler = _install_fleet_scheduler(monkeypatch)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    stream_scope = FleetTableStreamScope(game_id=628580, perspective=1, turn_number=111)

    def _failing_policy_factory(_stream_token: str):
        raise RuntimeError("policy construction failed")

    stream = iter_table_stream_connect_with_scope(
        begin_scope=lambda: scheduler.begin_scope(stream_scope),
        end_scope=lambda stream_token: scheduler.end_fleet_table_stream(
            stream_scope,
            (),
            stream_token=stream_token,
        ),
        policy_factory=_failing_policy_factory,
        player_ids=(),
    )
    with pytest.raises(RuntimeError, match="policy construction failed"):
        next(stream)

    assert not scheduler._scope_guard.has_active_table_stream

    replacement = iter_fleet_table_stream_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=persistence,
        scheduler=scheduler,
    )
    try:
        assert list(replacement) == []
    finally:
        replacement.close()
