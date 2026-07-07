"""Bounded LRU cache backed by OrderedDict."""

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
        """Return cached value and mark key as recently used, or None."""
        value = self._entries.get(key)
        if value is not None:
            self._entries.move_to_end(key)
        return value

    def put(self, key: K, value: V) -> None:
        """Insert or update and evict LRU entries when over capacity."""
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
