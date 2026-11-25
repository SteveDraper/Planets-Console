"""Tests for the backend-bound hull catalog mask override store."""

from __future__ import annotations

import threading

import pytest
from api.analytics.scores.hull_mask_overrides import (
    HullMaskOverrides,
    HullMaskSnapshot,
    clear_hull_mask_overrides,
    hull_mask_overrides_for,
)
from api.errors import NotFoundError
from api.storage.memory_asset import MemoryAssetBackend

GAME_ID = 628580
PLAYER_ID = 5
OTHER_PLAYER_ID = 6


class _CountingBackend(MemoryAssetBackend):
    """Memory backend that counts reads and can block a write until released."""

    def __init__(self) -> None:
        super().__init__(initial={})
        self.get_calls = 0
        self.put_started = threading.Event()
        self.release_put = threading.Event()
        self.release_put.set()

    def get(self, key: str):
        self.get_calls += 1
        return super().get(key)

    def put(self, key: str, value) -> None:
        self.put_started.set()
        assert self.release_put.wait(timeout=5)
        super().put(key, value)


def test_revision_of_an_unknown_key_is_zero_and_reads_no_storage():
    backend = _CountingBackend()
    store = HullMaskOverrides(backend)

    assert store.revision(GAME_ID, PLAYER_ID) == 0
    assert backend.get_calls == 0


def test_snapshot_loads_the_override_once_and_pairs_it_with_the_revision():
    backend = _CountingBackend()
    store = HullMaskOverrides(backend)

    first = store.snapshot(GAME_ID, PLAYER_ID)
    second = store.snapshot(GAME_ID, PLAYER_ID)

    assert first == HullMaskSnapshot(revision=0, user_override=None)
    assert second == first
    assert backend.get_calls == 1


def test_change_writes_storage_updates_the_cache_and_increments_the_revision():
    backend = MemoryAssetBackend(initial={})
    store = HullMaskOverrides(backend)

    store.change(GAME_ID, PLAYER_ID, frozenset({3, 1}))

    assert store.revision(GAME_ID, PLAYER_ID) == 1
    assert store.snapshot(GAME_ID, PLAYER_ID) == HullMaskSnapshot(
        revision=1, user_override=frozenset({1, 3})
    )
    assert HullMaskOverrides(backend).snapshot(GAME_ID, PLAYER_ID).user_override == frozenset(
        {1, 3}
    )
    assert store.revision(GAME_ID, OTHER_PLAYER_ID) == 0


def test_change_to_none_deletes_the_file_and_increments_the_revision():
    backend = MemoryAssetBackend(initial={})
    store = HullMaskOverrides(backend)
    store.change(GAME_ID, PLAYER_ID, frozenset({1}))

    store.change(GAME_ID, PLAYER_ID, None)

    assert store.snapshot(GAME_ID, PLAYER_ID) == HullMaskSnapshot(revision=2, user_override=None)
    with pytest.raises(NotFoundError):
        backend.get(store.mask_store_key(GAME_ID, PLAYER_ID))


def test_reset_with_no_stored_override_still_increments_the_revision():
    store = HullMaskOverrides(MemoryAssetBackend(initial={}))

    store.change(GAME_ID, PLAYER_ID, None)

    assert store.revision(GAME_ID, PLAYER_ID) == 1


def test_hold_and_change_on_the_same_key_serialise():
    store = HullMaskOverrides(MemoryAssetBackend(initial={}))
    changed = threading.Event()

    def change() -> None:
        store.change(GAME_ID, PLAYER_ID, frozenset({1}))
        changed.set()

    with store.hold(GAME_ID, PLAYER_ID):
        worker = threading.Thread(target=change)
        worker.start()
        assert not changed.wait(timeout=0.2)
        assert store.revision(GAME_ID, PLAYER_ID) == 0
    worker.join(timeout=5)
    assert changed.is_set()
    assert store.revision(GAME_ID, PLAYER_ID) == 1


def test_a_hold_on_one_key_does_not_block_another_key():
    store = HullMaskOverrides(MemoryAssetBackend(initial={}))
    changed = threading.Event()

    def change_other_player() -> None:
        store.change(GAME_ID, OTHER_PLAYER_ID, frozenset({1}))
        changed.set()

    with store.hold(GAME_ID, PLAYER_ID):
        worker = threading.Thread(target=change_other_player)
        worker.start()
        assert changed.wait(timeout=5)
    worker.join(timeout=5)


def test_revision_reads_do_not_wait_on_a_change_in_progress():
    backend = _CountingBackend()
    store = HullMaskOverrides(backend)
    backend.release_put.clear()
    worker = threading.Thread(target=store.change, args=(GAME_ID, PLAYER_ID, frozenset({1})))
    worker.start()
    assert backend.put_started.wait(timeout=5)

    assert store.revision(GAME_ID, PLAYER_ID) == 0

    backend.release_put.set()
    worker.join(timeout=5)
    assert store.revision(GAME_ID, PLAYER_ID) == 1


def test_hull_mask_overrides_for_is_one_instance_per_backend_until_cleared():
    backend = MemoryAssetBackend(initial={})
    other_backend = MemoryAssetBackend(initial={})

    store = hull_mask_overrides_for(backend)

    assert hull_mask_overrides_for(backend) is store
    assert hull_mask_overrides_for(other_backend) is not store
    clear_hull_mask_overrides()
    assert hull_mask_overrides_for(backend) is not store


def test_clear_backend_cache_drops_the_backend_bound_stores():
    from api.storage_factory import clear_backend_cache

    backend = MemoryAssetBackend(initial={})
    store = hull_mask_overrides_for(backend)

    clear_backend_cache()

    assert hull_mask_overrides_for(backend) is not store
