"""File-backend JSON-document LRU: admission, write-through, listings, isolation."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from api.config import ApiConfig, get_config, set_config
from api.errors import NotFoundError
from api.storage.document_lru import (
    LARGE_DOCUMENT_MIN_BYTES,
    FileBackendDocumentLru,
    admits_breakpoint_document,
    document_lru_for_root,
)
from api.storage.file import FileStorageBackend
from tests.file_backend_io_accounting import (
    ANALYTICS_PREFIX,
    FLEET_KEY,
    TURNS_PREFIX,
    FileIoCounts,
    count_file_backend_syscalls,
)

GAME_INFO = "games/628580/info"
TURN = "games/628580/1/turns/111"
TURN_NEXT = "games/628580/1/turns/112"
ACCOUNT = "credentials/accounts/alice"
ACCOUNT_BOB = "credentials/accounts/bob"
ACCOUNTS_PREFIX = "credentials/accounts"
FLEET = FLEET_KEY
SCORES = f"{ANALYTICS_PREFIX}/scores"
HOMEWORLD = f"{ANALYTICS_PREFIX}/homeworld-locator"


def _lru(storage_root: Path) -> FileBackendDocumentLru:
    """Return the process LRU for ``storage_root`` using the current config caps."""
    cfg = get_config()
    return document_lru_for_root(
        storage_root,
        small_document_maxsize=cfg.storage_small_document_lru_maxsize,
        large_document_maxsize=cfg.storage_large_document_lru_maxsize,
    )


def _document_lru(*, small: int, large: int) -> FileBackendDocumentLru:
    return FileBackendDocumentLru(
        small_document_maxsize=small,
        large_document_maxsize=large,
    )


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
    assert _lru(storage_root).has_document(FLEET)
    backend.delete(FLEET)
    assert not _lru(storage_root).has_document(FLEET)
    with pytest.raises(NotFoundError):
        backend.get(FLEET)


def test_turn_rst_is_not_retained(backend: FileStorageBackend, storage_root: Path) -> None:
    backend.put(TURN, {"turn": 111})
    lru = _lru(storage_root)
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
    lru = _lru(storage_root)
    assert not lru.has_document(ACCOUNT)
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        backend.get(ACCOUNT)
        backend.get(ACCOUNT)
    assert counts.json_load_calls == 2
    assert not lru.has_document(ACCOUNT)


def test_cache_caps_have_no_constructor_default() -> None:
    parameters = inspect.signature(FileBackendDocumentLru.__init__).parameters
    assert parameters["small_document_maxsize"].default is inspect.Parameter.empty
    assert parameters["large_document_maxsize"].default is inspect.Parameter.empty


def test_absent_config_uses_dataclass_cache_caps(storage_root: Path) -> None:
    previous = get_config()
    set_config(ApiConfig())
    try:
        backend = FileStorageBackend(storage_root)
        backend.put(FLEET, {"ledgers": {}})
        lru = _lru(storage_root)
        assert lru.small_document_maxsize() == 256
        assert lru.large_document_maxsize() == 16
        assert lru.has_small_document(FLEET)
        assert not lru.has_large_document(FLEET)
    finally:
        set_config(previous)


def test_document_lru_evicts_past_small_maxsize(storage_root: Path) -> None:
    previous = get_config()
    small_cap = 2
    set_config(
        ApiConfig(
            storage_small_document_lru_maxsize=small_cap,
            storage_large_document_lru_maxsize=2,
        )
    )
    try:
        backend = FileStorageBackend(storage_root)
        keys = [f"games/628580/1/turns/1/analytics/doc-{index}" for index in range(small_cap + 1)]
        for index, key in enumerate(keys):
            backend.put(key, {"n": index})
        lru = _lru(storage_root)
        assert lru.small_document_count() == small_cap
        assert lru.large_document_count() == 0
        assert not lru.has_document(keys[0])
        assert lru.has_document(keys[-1])
        counts = FileIoCounts()
        with count_file_backend_syscalls(counts):
            assert backend.get(keys[0]) == {"n": 0}
            assert backend.get(keys[-1]) == {"n": small_cap}
        assert counts.json_load_calls == 1
        assert counts.open_read_calls == 1
    finally:
        set_config(previous)


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
    assert _lru(root_a).has_document(FLEET)
    assert _lru(root_b).has_document(FLEET)
    assert _lru(root_a) is not _lru(root_b)


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


def test_list_turns_includes_new_turn_after_rst_put(backend: FileStorageBackend) -> None:
    backend.put(TURN, {"turn": 111})
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        first = backend.list(TURNS_PREFIX)
    assert first == ["111"]
    assert counts.iterdir_calls == 1

    backend.put(TURN_NEXT, {"turn": 112})
    counts.reset()
    with count_file_backend_syscalls(counts):
        second = backend.list(TURNS_PREFIX)
    assert second == ["111", "112"]
    assert counts.iterdir_calls == 1


def test_list_credentials_includes_new_account_after_put(backend: FileStorageBackend) -> None:
    backend.put(ACCOUNT, {"api_key": "a"})
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        first = backend.list(ACCOUNTS_PREFIX)
    assert first == ["alice"]
    assert counts.iterdir_calls == 1

    backend.put(ACCOUNT_BOB, {"api_key": "b"})
    counts.reset()
    with count_file_backend_syscalls(counts):
        second = backend.list(ACCOUNTS_PREFIX)
    assert second == ["alice", "bob"]
    assert counts.iterdir_calls == 1


def test_fill_document_installs_when_epoch_is_current() -> None:
    lru = _document_lru(small=4, large=4)
    _, epoch = lru.get_document(FLEET)
    lru.fill_document(FLEET, {"ledgers": {}}, epoch=epoch, byte_size=1)
    assert lru.has_small_document(FLEET)


def test_fill_document_after_delete_does_not_resurrect() -> None:
    lru = _document_lru(small=4, large=4)
    _, epoch = lru.get_document(FLEET)
    lru.remember_document(FLEET, {"ledgers": {}}, byte_size=1)
    lru.drop_document(FLEET)
    lru.fill_document(FLEET, {"ledgers": {"ghost": True}}, epoch=epoch, byte_size=1)
    assert not lru.has_document(FLEET)


def test_fill_listing_after_child_put_does_not_install_stale_names() -> None:
    lru = _document_lru(small=4, large=4)
    lru.remember_document(FLEET, {"ledgers": {}}, byte_size=1)
    _, epoch = lru.get_listing(ANALYTICS_PREFIX)
    lru.remember_document(SCORES, {"rows": {}}, byte_size=1)
    lru.fill_listing(ANALYTICS_PREFIX, ["fleet"], epoch=epoch)
    cached, _ = lru.get_listing(ANALYTICS_PREFIX)
    assert cached is None


def _json_string_file_size(text: str) -> int:
    """Byte size of a JSON string document plus the trailing newline the store writes."""
    return len(json.dumps(text).encode("utf-8")) + 1


def test_file_byte_size_selects_cache_and_put_can_cross(storage_root: Path) -> None:
    backend = FileStorageBackend(storage_root)
    under = "a" * (LARGE_DOCUMENT_MIN_BYTES - 4)
    at_threshold = "b" * (LARGE_DOCUMENT_MIN_BYTES - 3)
    assert _json_string_file_size(under) == LARGE_DOCUMENT_MIN_BYTES - 1
    assert _json_string_file_size(at_threshold) == LARGE_DOCUMENT_MIN_BYTES

    backend.put(FLEET, under)
    lru = _lru(storage_root)
    assert lru.has_small_document(FLEET)
    assert not lru.has_large_document(FLEET)

    backend.put(SCORES, at_threshold)
    assert lru.has_large_document(SCORES)
    assert not lru.has_small_document(SCORES)
    assert lru.has_small_document(FLEET)

    backend.put(FLEET, at_threshold)
    assert lru.has_large_document(FLEET)
    assert not lru.has_small_document(FLEET)
    counts = FileIoCounts()
    with count_file_backend_syscalls(counts):
        assert backend.get(FLEET) == at_threshold
        assert backend.get(SCORES) == at_threshold
    assert counts.json_load_calls == 0
    assert counts.open_read_calls == 0


def test_small_roster_and_large_documents_do_not_evict_each_other(storage_root: Path) -> None:
    previous = get_config()
    set_config(
        ApiConfig(
            storage_small_document_lru_maxsize=2,
            storage_large_document_lru_maxsize=1,
        )
    )
    try:
        backend = FileStorageBackend(storage_root)
        large = "c" * (LARGE_DOCUMENT_MIN_BYTES - 3)
        large_key = f"{ANALYTICS_PREFIX}/large"
        small_keys = [f"{ANALYTICS_PREFIX}/small-{index}" for index in range(2)]
        backend.put(large_key, large)
        for key in small_keys:
            backend.put(key, {"n": key})
        lru = _lru(storage_root)
        assert lru.large_document_count() == 1
        assert lru.small_document_count() == 2
        assert lru.has_large_document(large_key)

        backend.put(f"{ANALYTICS_PREFIX}/small-extra", {"n": "extra"})
        assert lru.has_large_document(large_key)
        assert lru.small_document_count() == 2
        assert not lru.has_small_document(small_keys[0])

        second_large = f"{ANALYTICS_PREFIX}/large-2"
        backend.put(second_large, large)
        assert lru.has_large_document(second_large)
        assert not lru.has_large_document(large_key)
        assert lru.has_small_document(small_keys[1])
        assert lru.has_small_document(f"{ANALYTICS_PREFIX}/small-extra")
        counts = FileIoCounts()
        with count_file_backend_syscalls(counts):
            assert backend.get(small_keys[1]) == {"n": small_keys[1]}
            assert backend.get(second_large) == large
        assert counts.json_load_calls == 0
    finally:
        set_config(previous)
