"""File-backend JSON-document LRU: admission, write-through, listings, isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from api.errors import NotFoundError
from api.storage.document_lru import (
    FILE_DOCUMENT_LRU_MAXSIZE,
    admits_breakpoint_document,
    document_lru_for_root,
)
from api.storage.file import FileStorageBackend
from tests.file_backend_io_accounting import (
    ANALYTICS_PREFIX,
    FLEET_KEY,
    FileIoCounts,
    count_file_backend_syscalls,
)

GAME_INFO = "games/628580/info"
TURN = "games/628580/1/turns/111"
ACCOUNT = "credentials/accounts/alice"
FLEET = FLEET_KEY
SCORES = f"{ANALYTICS_PREFIX}/scores"
HOMEWORLD = f"{ANALYTICS_PREFIX}/homeworld-locator"


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def backend(storage_root: Path) -> FileStorageBackend:
    return FileStorageBackend(storage_root)


def test_admits_analytic_and_game_info_not_turn_or_credentials() -> None:
    assert admits_breakpoint_document(GAME_INFO)
    assert admits_breakpoint_document(FLEET)
    assert admits_breakpoint_document("games/628580/analytics/scores")
    assert admits_breakpoint_document("games/628580/1/analytics/homeworld-locator")
    assert not admits_breakpoint_document(TURN)
    assert not admits_breakpoint_document(ACCOUNT)


def test_second_get_of_admitted_document_is_cache_hit(
    backend: FileStorageBackend, storage_root: Path
) -> None:
    fleet_path = storage_root / "games/628580/1/turns/111/analytics/fleet.json"
    fleet_path.parent.mkdir(parents=True)
    fleet_path.write_text('{"ledgers": {}}\n', encoding="utf-8")
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        first = backend.get(FLEET)
        second = backend.get(FLEET)
    assert first == {"ledgers": {}}
    assert second == {"ledgers": {}}
    assert counts.json_load_calls == 1
    assert counts.open_read_calls == 1


def test_put_then_get_is_write_through_hit(backend: FileStorageBackend) -> None:
    backend.put(FLEET, {"ledgers": {"p": 1}})
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        loaded = backend.get(FLEET)
    assert loaded == {"ledgers": {"p": 1}}
    assert counts.json_load_calls == 0
    assert counts.open_read_calls == 0


def test_suffix_put_then_get_returns_merged_from_cache(backend: FileStorageBackend) -> None:
    backend.put(GAME_INFO, {"name": "Serada"})
    backend.put(f"{GAME_INFO}/settings", {"x": 1})
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        loaded = backend.get(GAME_INFO)
    assert loaded == {"name": "Serada", "settings": {"x": 1}}
    assert counts.json_load_calls == 0
    assert counts.open_read_calls == 0


def test_delete_then_get_raises_and_drops_entry(
    backend: FileStorageBackend, storage_root: Path
) -> None:
    backend.put(FLEET, {"ledgers": {}})
    assert document_lru_for_root(storage_root).has_document(FLEET)
    backend.delete(FLEET)
    assert not document_lru_for_root(storage_root).has_document(FLEET)
    with pytest.raises(NotFoundError):
        backend.get(FLEET)


def test_turn_rst_is_not_retained(backend: FileStorageBackend, storage_root: Path) -> None:
    backend.put(TURN, {"turn": 111})
    lru = document_lru_for_root(storage_root)
    assert not lru.has_document(TURN)
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        backend.get(TURN)
        backend.get(TURN)
    assert counts.json_load_calls == 2
    assert counts.open_read_calls == 2
    assert not lru.has_document(TURN)


def test_credentials_are_not_retained(backend: FileStorageBackend, storage_root: Path) -> None:
    backend.put(ACCOUNT, {"api_key": "secret"})
    lru = document_lru_for_root(storage_root)
    assert not lru.has_document(ACCOUNT)
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        backend.get(ACCOUNT)
        backend.get(ACCOUNT)
    assert counts.json_load_calls == 2
    assert not lru.has_document(ACCOUNT)


def test_document_lru_evicts_past_maxsize(backend: FileStorageBackend, storage_root: Path) -> None:
    keys = [
        f"games/628580/1/turns/1/analytics/doc-{index}"
        for index in range(FILE_DOCUMENT_LRU_MAXSIZE + 1)
    ]
    for index, key in enumerate(keys):
        backend.put(key, {"n": index})
    lru = document_lru_for_root(storage_root)
    assert lru.document_count() == FILE_DOCUMENT_LRU_MAXSIZE
    assert not lru.has_document(keys[0])
    assert lru.has_document(keys[-1])
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        assert backend.get(keys[0]) == {"n": 0}
        assert backend.get(keys[-1]) == {"n": FILE_DOCUMENT_LRU_MAXSIZE}
    assert counts.json_load_calls == 1
    assert counts.open_read_calls == 1


def test_same_root_backends_share_hits(storage_root: Path) -> None:
    first = FileStorageBackend(storage_root)
    second = FileStorageBackend(storage_root.resolve())
    first.put(FLEET, {"shared": True})
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        loaded = second.get(FLEET)
    assert loaded == {"shared": True}
    assert counts.json_load_calls == 0
    assert counts.open_read_calls == 0


def test_different_roots_do_not_share_entries(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    backend_a = FileStorageBackend(root_a)
    backend_b = FileStorageBackend(root_b)
    backend_a.put(FLEET, {"root": "a"})
    backend_b.put(FLEET, {"root": "b"})
    assert backend_a.get(FLEET) == {"root": "a"}
    assert backend_b.get(FLEET) == {"root": "b"}
    assert document_lru_for_root(root_a).has_document(FLEET)
    assert document_lru_for_root(root_b).has_document(FLEET)
    assert document_lru_for_root(root_a) is not document_lru_for_root(root_b)


def test_list_analytics_prefix_is_cached_and_invalidated_on_child_put_delete(
    backend: FileStorageBackend,
) -> None:
    backend.put(FLEET, {"ledgers": {}})
    backend.put(SCORES, {"rows": {}})
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        first = backend.list(ANALYTICS_PREFIX)
        second = backend.list(ANALYTICS_PREFIX)
    assert first == ["fleet", "scores"]
    assert second == ["fleet", "scores"]
    assert counts.iterdir_calls == 1
    assert counts.json_load_calls == 0

    counts.reset()
    with count_file_backend_syscalls(counts):
        backend.put(HOMEWORLD, {"evidence": {}})
    counts.reset()
    with count_file_backend_syscalls(counts):
        after_put = backend.list(ANALYTICS_PREFIX)
    assert after_put == ["fleet", "homeworld-locator", "scores"]
    assert counts.iterdir_calls == 1

    backend.delete(HOMEWORLD)
    counts.reset()
    with count_file_backend_syscalls(counts):
        after_delete = backend.list(ANALYTICS_PREFIX)
    assert after_delete == ["fleet", "scores"]
    assert counts.iterdir_calls == 1


def test_get_returns_deep_copy_of_cached_document(backend: FileStorageBackend) -> None:
    backend.put(FLEET, {"ledgers": {"p": 1}})
    loaded = backend.get(FLEET)
    assert isinstance(loaded, dict)
    loaded["ledgers"] = {}
    assert backend.get(FLEET) == {"ledgers": {"p": 1}}
