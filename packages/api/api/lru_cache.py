"""Bounded LRU cache backed by OrderedDict.

Shared by the file-backend document cache and the process TurnInfo cache.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LruCache(Generic[K, V]):
    """Insert-or-update with move-to-end; evict least-recently-used past maxsize."""

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._entries: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        """Return cached value and mark key as recently used, or None if absent."""
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key: K, value: V) -> None:
        """Insert or update and evict LRU entries when over capacity."""
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)

    def drop(self, key: K) -> None:
        """Remove ``key`` if present; missing keys are a no-op."""
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)
