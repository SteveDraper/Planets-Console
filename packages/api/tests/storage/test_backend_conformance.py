"""Shared StorageBackend contract tests for ephemeral and file backends."""

from __future__ import annotations

import pytest
from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend
from api.storage.file import FileStorageBackend
from api.storage.memory_asset import MemoryAssetBackend

GAME_INFO = "games/sample/info"
GAME_NESTED = f"{GAME_INFO}/settings"
TURN = "games/sample/1/turns/111"
TURN_SHIP = f"{TURN}/ships/@0"
ACCOUNT = "credentials/accounts/alice"
ACCOUNT_KEY = f"{ACCOUNT}/api_key"


@pytest.fixture(params=["ephemeral", "file"])
def backend(request, tmp_path) -> StorageBackend:
    if request.param == "ephemeral":
        return MemoryAssetBackend(initial={})
    return FileStorageBackend(tmp_path / "data")


def test_put_get_delete_document(backend):
    backend.put(GAME_INFO, {"name": "Test Game", "turn": 1})
    assert backend.get(GAME_INFO) == {"name": "Test Game", "turn": 1}
    backend.delete(GAME_INFO)
    with pytest.raises(NotFoundError):
        backend.get(GAME_INFO)


def test_put_get_nested_in_document(backend):
    backend.put(GAME_NESTED, {"difficulty": "hard"})
    assert backend.get(GAME_NESTED) == {"difficulty": "hard"}
    assert backend.get(GAME_INFO) == {"settings": {"difficulty": "hard"}}


def test_put_overwrites_existing(backend):
    backend.put(f"{GAME_INFO}/turn", 1)
    backend.put(f"{GAME_INFO}/turn", 2)
    assert backend.get(f"{GAME_INFO}/turn") == 2


def test_array_index_get_put_delete(backend):
    backend.put(TURN, {"ships": [{"id": 1}, {"id": 2}]})
    assert backend.get(TURN_SHIP) == {"id": 1}
    backend.put(TURN_SHIP, {"id": 99})
    assert backend.get(TURN_SHIP) == {"id": 99}
    backend.delete(TURN_SHIP)
    assert backend.get(f"{TURN}/ships") == [{"id": 2}]


def test_array_append(backend):
    backend.put(TURN, {"ships": [{"id": 1}]})
    backend.put(f"{TURN}/ships/@1", {"id": 2})
    assert backend.get(f"{TURN}/ships") == [{"id": 1}, {"id": 2}]


def test_credentials_document(backend):
    backend.put(ACCOUNT_KEY, "secret")
    assert backend.get(ACCOUNT_KEY) == "secret"
    assert backend.get(ACCOUNT) == {"api_key": "secret"}


def test_root_list_only(backend):
    backend.put(GAME_INFO, {"name": "A"})
    backend.put(ACCOUNT, {"api_key": "k"})
    assert set(backend.list("")) == {"games", "credentials"}
    with pytest.raises(ValidationError, match="Cannot get root"):
        backend.get("")
    with pytest.raises(ValidationError, match="Cannot put root"):
        backend.put("", {})
    with pytest.raises(ValidationError, match="Cannot delete root"):
        backend.delete("")


def test_unregistered_path_rejected(backend):
    with pytest.raises(ValidationError, match="Unregistered"):
        backend.get("unknown/path")
    with pytest.raises(ValidationError, match="Unregistered"):
        backend.put("unknown/path", 1)
    with pytest.raises(ValidationError, match="Unregistered"):
        backend.delete("unknown/path")
    with pytest.raises(ValidationError, match="Unregistered"):
        backend.list("unknown/path")


def test_list_prefix(backend):
    backend.put(GAME_INFO, {"name": "A", "meta": {"x": 1}})
    assert backend.list("games") == ["sample"]
    assert set(backend.list("games/sample/info")) == {"name", "meta"}
    assert backend.list(f"{GAME_INFO}/meta") == ["x"]


def test_list_missing_raises(backend):
    with pytest.raises(NotFoundError):
        backend.list("games/missing/info")


def test_get_missing_raises(backend):
    with pytest.raises(NotFoundError):
        backend.get(GAME_INFO)


def test_delete_missing_raises(backend):
    with pytest.raises(NotFoundError):
        backend.delete(GAME_INFO)


def test_get_returns_deep_copy(backend):
    backend.put(GAME_INFO, {"name": "A"})
    value = backend.get(GAME_INFO)
    assert isinstance(value, dict)
    value["name"] = "mutated"
    assert backend.get(GAME_INFO) == {"name": "A"}
