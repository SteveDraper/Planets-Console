"""Per-(game, player) hull catalog mask overrides and their revisions.

``HullMaskOverrides`` is the only owner of the stored mask override file
(``games/{game}/analytics/scores/inference_hull_catalog_masks/{player}``). A
mask override applies to one player across every turn and perspective of a
game, so the store is keyed by (game, player).

Each key carries a **hull mask revision** that every save or reset increments.
The scores epoch adds it, so a mask change moves the epoch of the player's
scores scopes at every turn and perspective.

Lifetime: one instance per storage backend (:func:`hull_mask_overrides_for`),
not per service stack, because the Core REST API builds a stack per request
while the orchestrator reads epochs for the life of the process. The instances
are dropped with their backend and by :func:`clear_hull_mask_overrides`
(called from ``clear_backend_cache``). Revisions are in memory only: they
guard in-memory ladders, which a restart drops too.

Locks: each key has its own lock, held by :meth:`HullMaskOverrides.change`
across the storage write and the increment, and by
:meth:`HullMaskOverrides.hold` for callers that must not interleave with a
change. :meth:`HullMaskOverrides.revision` takes no lock, so the
orchestrator, which reads epochs under its own lock, never waits on a key
lock. Under a key lock a caller may take fleet persistence's generation lock;
nothing takes a key lock while holding the orchestrator's lock.
"""

from __future__ import annotations

import threading
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from api.analytics.military_score_inference.hull_catalog_mask import (
    ResolvedHullCatalogMask,
    resolve_hull_catalog_mask,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.errors import NotFoundError, ValidationError
from api.models.game import TurnInfo
from api.serialization.inference_hull_catalog import (
    InferenceHullCatalogMaskOverride,
    inference_hull_catalog_mask_override_from_json,
    inference_hull_catalog_mask_override_to_json,
)
from api.storage.base import StorageBackend

_INFERENCE_HULL_CATALOG_MASKS_KEY = "inference_hull_catalog_masks"

_MaskKey = tuple[int, int]


@dataclass(frozen=True, slots=True)
class HullMaskSnapshot:
    """One key's revision and user override, read together."""

    revision: int
    user_override: frozenset[int] | None


class HullMaskOverrides:
    """Stored hull catalog mask overrides with a revision per (game, player)."""

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage
        self._locks_guard = threading.Lock()
        self._locks: dict[_MaskKey, threading.RLock] = {}
        self._revisions: dict[_MaskKey, int] = {}
        # Loaded on first snapshot; absent means not yet read from storage.
        self._overrides: dict[_MaskKey, frozenset[int] | None] = {}

    def mask_store_key(self, game_id: int, player_id: int) -> str:
        return (
            f"games/{game_id}/analytics/{SCORES_ANALYTIC_ID}/"
            f"{_INFERENCE_HULL_CATALOG_MASKS_KEY}/{player_id}"
        )

    def revision(self, game_id: int, player_id: int) -> int:
        """The key's revision, 0 when it never changed in this process. Takes no lock."""
        return self._revisions.get((game_id, player_id), 0)

    def snapshot(self, game_id: int, player_id: int) -> HullMaskSnapshot:
        """The key's revision and user override, read in one hold of its lock."""
        key = (game_id, player_id)
        with self._lock_for(key):
            return HullMaskSnapshot(
                revision=self._revisions.get(key, 0),
                user_override=self._override_locked(key),
            )

    def effective_mask(
        self, turn: TurnInfo, game_id: int, player_id: int
    ) -> ResolvedHullCatalogMask:
        """The player's hull catalog mask on ``turn`` under their current stored override."""
        user_override = self.snapshot(game_id, player_id).user_override
        return resolve_hull_catalog_mask(turn, player_id, user_enabled_hull_ids=user_override)

    def change(self, game_id: int, player_id: int, override: frozenset[int] | None) -> None:
        """Store ``override`` (None deletes it) and increment the revision, in one hold."""
        key = (game_id, player_id)
        with self._lock_for(key):
            store_key = self.mask_store_key(game_id, player_id)
            if override is None:
                try:
                    self._storage.delete(store_key)
                except NotFoundError:
                    pass
            else:
                self._storage.put(
                    store_key,
                    inference_hull_catalog_mask_override_to_json(
                        InferenceHullCatalogMaskOverride(enabled_hull_ids=sorted(override))
                    ),
                )
            self._overrides[key] = override
            self._revisions[key] = self._revisions.get(key, 0) + 1

    @contextmanager
    def hold(self, game_id: int, player_id: int) -> Iterator[None]:
        """Hold the key's lock, so no change to that key lands inside the block."""
        with self._lock_for((game_id, player_id)):
            yield

    def _lock_for(self, key: _MaskKey) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock

    def _override_locked(self, key: _MaskKey) -> frozenset[int] | None:
        """The cached override, loading it from storage first. Caller holds the key's lock."""
        if key not in self._overrides:
            self._overrides[key] = self._load_override(*key)
        return self._overrides[key]

    def _load_override(self, game_id: int, player_id: int) -> frozenset[int] | None:
        try:
            data = self._storage.get(self.mask_store_key(game_id, player_id))
        except NotFoundError:
            return None
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError("stored hull catalog mask override must be a JSON object")
        override = inference_hull_catalog_mask_override_from_json(data)
        return frozenset(override.enabled_hull_ids)


_instances_lock = threading.Lock()
_instances: weakref.WeakKeyDictionary[StorageBackend, HullMaskOverrides] = (
    weakref.WeakKeyDictionary()
)


def hull_mask_overrides_for(storage: StorageBackend) -> HullMaskOverrides:
    """The one mask override store for ``storage``, created on first use."""
    with _instances_lock:
        store = _instances.get(storage)
        if store is None:
            store = HullMaskOverrides(storage)
            _instances[storage] = store
        return store


def clear_hull_mask_overrides() -> None:
    """Drop every backend's store and its revisions (backend reset and tests)."""
    with _instances_lock:
        _instances.clear()
