"""Backfill earlier turns: one boolean per game, read without submitting a walk."""

import json
import logging
import threading
from pathlib import Path

import pytest
from api.analytics.export_context import (
    AnalyticQueryContext,
    backfill_earlier_turns_disabled,
)
from api.analytics.on_walk_live import submit_on_walks_for_live_streams
from api.analytics.options import TurnAnalyticsOptions
from api.compute.orchestrator_submission import OrchestratorSubmissionMixin
from api.config import ApiConfig, set_config
from api.errors import NotFoundError, ValidationError
from api.serialization.backfill_earlier_turns import (
    BACKFILL_EARLIER_TURNS_FIELD,
    backfill_earlier_turns_document,
    backfill_earlier_turns_reader,
    backfill_earlier_turns_store_key,
    read_backfill_earlier_turns,
)
from api.services.game_service import GameService
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend
from api.storage_factory import clear_backend_cache, get_storage
from fastapi.testclient import TestClient

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
_GAME_ID = 628580


def _sample_game_info() -> dict:
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        return json.load(handle)


def _sample_turn() -> dict:
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        return json.load(handle)


@pytest.fixture
def storage():
    backend = MemoryAssetBackend(initial={})
    backend.put(f"games/{_GAME_ID}/info", _sample_game_info())
    backend.put(f"games/{_GAME_ID}/1/turns/111", _sample_turn())
    return backend


@pytest.fixture
def service(storage):
    return GameService(storage)


def _reject_compute_submit(monkeypatch) -> list:
    submitted: list = []

    def submit(self, request):
        submitted.append(request)

    monkeypatch.setattr(OrchestratorSubmissionMixin, "submit", submit)
    return submitted


def test_missing_record_reads_off_and_does_not_create_one(service, storage):
    assert service.get_backfill_earlier_turns(_GAME_ID) is False
    with pytest.raises(NotFoundError):
        storage.get(backfill_earlier_turns_store_key(_GAME_ID))


def test_missing_game_matches_get_game_info(service):
    with pytest.raises(NotFoundError) as backfill_missing:
        service.get_backfill_earlier_turns(999999)
    with pytest.raises(NotFoundError) as info_missing:
        service.get_game_info(999999)
    assert str(backfill_missing.value) == str(info_missing.value)


def test_checkbox_value_is_one_record_for_the_game_and_survives_reload(service, storage):
    assert service.set_backfill_earlier_turns(_GAME_ID, True) is True
    assert storage.get(backfill_earlier_turns_store_key(_GAME_ID)) == {
        BACKFILL_EARLIER_TURNS_FIELD: True
    }
    info = storage.get(f"games/{_GAME_ID}/info")
    assert BACKFILL_EARLIER_TURNS_FIELD not in json.dumps(info)

    reloaded = GameService(storage)
    assert reloaded.get_backfill_earlier_turns(_GAME_ID) is True

    storage.put(f"games/{_GAME_ID}/info", _sample_game_info())
    assert reloaded.get_backfill_earlier_turns(_GAME_ID) is True

    turns = build_service_stack(storage).turns
    assert turns.list_stored_turn_perspectives(_GAME_ID, 111) == [1]


def test_explicit_false_is_stored_and_still_reads_off(service, storage):
    service.set_backfill_earlier_turns(_GAME_ID, False)
    assert service.get_backfill_earlier_turns(_GAME_ID) is False
    assert storage.get(backfill_earlier_turns_store_key(_GAME_ID)) == {
        BACKFILL_EARLIER_TURNS_FIELD: False
    }


def test_off_to_on_notifies_once(storage):
    notified: list[int] = []
    service = GameService(storage, on_backfill_enabled=notified.append)
    service.set_backfill_earlier_turns(_GAME_ID, False)
    assert notified == []
    service.set_backfill_earlier_turns(_GAME_ID, True)
    assert notified == [_GAME_ID]
    service.set_backfill_earlier_turns(_GAME_ID, True)
    assert notified == [_GAME_ID]
    service.set_backfill_earlier_turns(_GAME_ID, False)
    assert notified == [_GAME_ID]
    service.set_backfill_earlier_turns(_GAME_ID, True)
    assert notified == [_GAME_ID, _GAME_ID]


def test_failing_listener_does_not_fail_the_save(storage, caplog):
    def fail(game_id: int) -> None:
        raise RuntimeError("scan blew up")

    service = GameService(storage, on_backfill_enabled=fail)
    with caplog.at_level(logging.ERROR, logger="api.services.game_service"):
        assert service.set_backfill_earlier_turns(_GAME_ID, True) is True
    assert read_backfill_earlier_turns(storage, _GAME_ID) is True
    failures = [record for record in caplog.records if record.exc_info is not None]
    assert len(failures) == 1
    assert str(_GAME_ID) in failures[0].getMessage()
    assert failures[0].exc_info[1].args == ("scan blew up",)


class _ReadersMeetStorage:
    """Holds each finished Backfill earlier turns read until a second reader or a timeout."""

    def __init__(self, inner: MemoryAssetBackend) -> None:
        self._inner = inner
        self._readers_meet = threading.Barrier(2, timeout=0.2)

    def get(self, key: str):
        if key != backfill_earlier_turns_store_key(_GAME_ID):
            return self._inner.get(key)
        try:
            return self._inner.get(key)
        finally:
            try:
                self._readers_meet.wait()
            except threading.BrokenBarrierError:
                pass

    def put(self, key: str, value) -> None:
        self._inner.put(key, value)

    def delete(self, key: str) -> None:
        self._inner.delete(key)

    def list(self, prefix: str) -> list[str]:
        return self._inner.list(prefix)


def test_concurrent_enables_notify_once(storage):
    shared = _ReadersMeetStorage(storage)
    notified: list[int] = []
    services = [GameService(shared, on_backfill_enabled=notified.append) for _ in range(2)]
    writers = [
        threading.Thread(target=service.set_backfill_earlier_turns, args=(_GAME_ID, True))
        for service in services
    ]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()
    assert notified == [_GAME_ID]
    assert read_backfill_earlier_turns(storage, _GAME_ID) is True


def test_service_stack_submits_live_on_walks_when_backfill_turns_on(storage):
    stack = build_service_stack(storage)
    assert stack.games._on_backfill_enabled is submit_on_walks_for_live_streams


def test_read_and_write_submit_no_walk(service, monkeypatch):
    submitted = _reject_compute_submit(monkeypatch)
    assert service.get_backfill_earlier_turns(_GAME_ID) is False
    service.set_backfill_earlier_turns(_GAME_ID, True)
    assert service.get_backfill_earlier_turns(_GAME_ID) is True
    assert submitted == []


def test_malformed_record_is_rejected(service, storage):
    key = backfill_earlier_turns_store_key(_GAME_ID)
    storage.put(key, {BACKFILL_EARLIER_TURNS_FIELD: "yes"})
    with pytest.raises(ValidationError, match="boolean"):
        service.get_backfill_earlier_turns(_GAME_ID)

    storage.put(key, {BACKFILL_EARLIER_TURNS_FIELD: True, "walkProgress": 1})
    with pytest.raises(ValidationError, match="only backfillEarlierTurns"):
        service.get_backfill_earlier_turns(_GAME_ID)


def test_read_record_is_off_when_missing_and_rejects_a_bad_document():
    storage = MemoryAssetBackend(initial={})
    assert read_backfill_earlier_turns(storage, _GAME_ID) is False
    with pytest.raises(NotFoundError):
        storage.get(backfill_earlier_turns_store_key(_GAME_ID))

    key = backfill_earlier_turns_store_key(_GAME_ID)
    storage.put(key, ["on"])
    with pytest.raises(ValidationError, match="Expected JSON object"):
        read_backfill_earlier_turns(storage, _GAME_ID)

    storage.put(key, {BACKFILL_EARLIER_TURNS_FIELD: "yes"})
    with pytest.raises(ValidationError, match="boolean"):
        read_backfill_earlier_turns(storage, _GAME_ID)

    storage.put(key, {BACKFILL_EARLIER_TURNS_FIELD: True, "walkProgress": 1})
    with pytest.raises(ValidationError, match="only backfillEarlierTurns"):
        read_backfill_earlier_turns(storage, _GAME_ID)

    storage.put(key, {BACKFILL_EARLIER_TURNS_FIELD: True})
    assert read_backfill_earlier_turns(storage, _GAME_ID) is True


def test_set_rejects_non_boolean_and_missing_game(service, storage):
    with pytest.raises(ValidationError, match="boolean"):
        service.set_backfill_earlier_turns(_GAME_ID, 1)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        storage.get(backfill_earlier_turns_store_key(_GAME_ID))

    with pytest.raises(NotFoundError):
        service.set_backfill_earlier_turns(999999, True)


@pytest.fixture
def client():
    clear_backend_cache()
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    stored = get_storage()
    stored.put(f"games/{_GAME_ID}/info", _sample_game_info())
    from api.app import app

    yield TestClient(app, raise_server_exceptions=False)
    clear_backend_cache()


def test_core_http_reads_the_checkbox_value_back(client):
    missing = client.get(f"/v1/games/{_GAME_ID}/backfill-earlier-turns")
    assert missing.status_code == 200
    assert missing.json() == {BACKFILL_EARLIER_TURNS_FIELD: False}

    saved = client.put(
        f"/v1/games/{_GAME_ID}/backfill-earlier-turns",
        json={BACKFILL_EARLIER_TURNS_FIELD: True},
    )
    assert saved.status_code == 200
    assert saved.json() == {BACKFILL_EARLIER_TURNS_FIELD: True}

    again = client.get(f"/v1/games/{_GAME_ID}/backfill-earlier-turns")
    assert again.json() == {BACKFILL_EARLIER_TURNS_FIELD: True}

    info = client.get(f"/v1/games/{_GAME_ID}/info")
    assert info.status_code == 200
    assert BACKFILL_EARLIER_TURNS_FIELD not in info.text


def test_core_http_missing_game_matches_game_info(client):
    backfill = client.get("/v1/games/999999/backfill-earlier-turns")
    info = client.get("/v1/games/999999/info")
    assert backfill.status_code == 404
    assert backfill.json() == info.json()


def test_core_http_rejects_extra_fields(client):
    response = client.put(
        f"/v1/games/{_GAME_ID}/backfill-earlier-turns",
        json={BACKFILL_EARLIER_TURNS_FIELD: True, "walkProgress": 1},
    )
    assert response.status_code == 422


def _query_context(reader) -> AnalyticQueryContext:
    return AnalyticQueryContext(
        game_id=_GAME_ID,
        perspective=1,
        ambient_turn=1,
        options=TurnAnalyticsOptions(),
        load_turn=lambda _turn: None,
        export_registry={},
        read_backfill_earlier_turns=reader,
    )


def test_reader_binds_storage_and_context_uses_it():
    storage = MemoryAssetBackend(initial={})
    reader = backfill_earlier_turns_reader(storage)
    ctx = _query_context(reader)
    assert ctx.backfill_earlier_turns_enabled() is False

    storage.put(
        backfill_earlier_turns_store_key(_GAME_ID),
        backfill_earlier_turns_document(True),
    )
    assert ctx.backfill_earlier_turns_enabled() is True


def test_context_without_reader_raises_instead_of_reporting_off():
    ctx = AnalyticQueryContext(
        game_id=_GAME_ID,
        perspective=1,
        ambient_turn=1,
        options=TurnAnalyticsOptions(),
        load_turn=lambda _turn: None,
        export_registry={},
    )
    with pytest.raises(RuntimeError, match="no Backfill earlier turns reader"):
        ctx.backfill_earlier_turns_enabled()


def test_disabled_reader_stays_off_when_storage_is_on():
    storage = MemoryAssetBackend(initial={})
    storage.put(
        backfill_earlier_turns_store_key(_GAME_ID),
        backfill_earlier_turns_document(True),
    )
    ctx = _query_context(backfill_earlier_turns_disabled)
    assert read_backfill_earlier_turns(storage, _GAME_ID) is True
    assert ctx.backfill_earlier_turns_enabled() is False
