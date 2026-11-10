"""Per-player fleet evidence marks: durable document, process cache, and assumed overlay."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType

from api.analytics.fleet.constants import FLEET_EVIDENCE_MARK_SEGMENT
from api.analytics.fleet.serialization import (
    fleet_evidence_mark_from_json,
    fleet_evidence_mark_to_json,
)
from api.analytics.fleet.stored_documents import (
    delete_if_present,
    list_segments,
    read_json_object,
)
from api.analytics.fleet.types import FleetEvidenceMark
from api.storage.base import StorageBackend

_ABSENT_EVIDENCE_MARK = FleetEvidenceMark()

_EvidenceMarkKey = tuple[int, int, int]
_assumed_evidence_marks: ContextVar[Mapping[_EvidenceMarkKey, FleetEvidenceMark]] = ContextVar(
    "assumed_fleet_evidence_marks",
    default=MappingProxyType({}),
)


class FleetEvidenceMarkStore:
    """Evidence mark per ``(game, perspective, player)``.

    Path: ``games/{gameId}/{perspective}/analytics/fleet-evidence/{playerId}``.

    ``lock`` is the owning persistence service's generation lock. Every
    read-modify-write here runs under it, so a caller that already holds it
    (a ledger stamp, a durable invalidation) composes mark and epoch changes in
    one hold. The lock must be re-entrant.
    """

    def __init__(self, storage: StorageBackend, lock: threading.RLock) -> None:
        self._storage = storage
        self._lock = lock
        self._cache: dict[_EvidenceMarkKey, FleetEvidenceMark] = {}

    @staticmethod
    def key(game_id: int, perspective: int, player_id: int) -> str:
        return f"games/{game_id}/{perspective}/analytics/{FLEET_EVIDENCE_MARK_SEGMENT}/{player_id}"

    def get(self, game_id: int, perspective: int, player_id: int) -> FleetEvidenceMark:
        """The stored mark, or the mark assumed in this context while none is stored."""
        key = (game_id, perspective, player_id)
        stored = self._stored(key)
        if stored != _ABSENT_EVIDENCE_MARK:
            return stored
        return _assumed_evidence_marks.get().get(key, stored)

    @contextmanager
    def assuming(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        mark: FleetEvidenceMark,
    ) -> Iterator[None]:
        """Read ``mark`` for this player in the calling context while no mark is stored.

        Nothing is written. Other threads, and a mark that is stored, are
        unaffected. ``update`` always sees the stored mark.
        """
        assumed = dict(_assumed_evidence_marks.get())
        assumed[(game_id, perspective, player_id)] = mark
        token = _assumed_evidence_marks.set(MappingProxyType(assumed))
        try:
            yield
        finally:
            _assumed_evidence_marks.reset(token)

    def update(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        update: Callable[[FleetEvidenceMark], FleetEvidenceMark],
    ) -> FleetEvidenceMark:
        """Replace one player's evidence mark under the generation lock.

        ``update`` sees the mark currently stored and returns the mark to
        keep. An equal result is not written again.
        """
        key = (game_id, perspective, player_id)
        with self._lock:
            current = self._stored(key)
            updated = update(current)
            if updated != current:
                self._write(key, updated)
            self._cache[key] = updated
            return updated

    def bump_durable(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        host_turn: int,
    ) -> FleetEvidenceMark:
        """Advance the mark. Do not move ``appliesFromTurn`` forward over a gap."""
        key = (game_id, perspective, player_id)
        with self._lock:
            current = self._cached_or_read(key)
            applies_from = current.applies_from_turn
            if applies_from is None or host_turn < applies_from:
                applies_from = host_turn
            updated = FleetEvidenceMark(
                evidence_generation=current.evidence_generation + 1,
                applies_from_turn=applies_from,
            )
            self._write(key, updated)
            self._cache[key] = updated
            return updated

    def advance_after_boundary_write(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        turn_number: int,
        evidence_generation: int,
    ) -> None:
        """After a final ledger at the bound, the next turn is the new bound.

        The generation is unchanged. A crash before this write leaves the bound
        on the turn just stored; that ledger still matches the generation, and
        later turns do not.
        """
        key = (game_id, perspective, player_id)
        with self._lock:
            current = self._cached_or_read(key)
            if current.applies_from_turn != turn_number:
                return
            if current.evidence_generation != evidence_generation:
                return
            updated = FleetEvidenceMark(
                evidence_generation=current.evidence_generation,
                applies_from_turn=turn_number + 1,
            )
            self._write(key, updated)
            self._cache[key] = updated

    def delete(self, game_id: int, perspective: int, player_id: int) -> bool:
        """Remove one player's evidence mark. Return whether a file was deleted."""
        deleted = delete_if_present(self._storage, self.key(game_id, perspective, player_id))
        with self._lock:
            self._cache.pop((game_id, perspective, player_id), None)
        return deleted

    def delete_all(self, game_id: int, perspective: int) -> list[str]:
        """Remove every evidence mark for one perspective. Return deleted keys."""
        prefix = f"games/{game_id}/{perspective}/analytics/{FLEET_EVIDENCE_MARK_SEGMENT}"
        deleted: list[str] = []
        for segment in list_segments(self._storage, prefix):
            if not segment.isdigit():
                continue
            player_id = int(segment)
            key = self.key(game_id, perspective, player_id)
            if self.delete(game_id, perspective, player_id):
                deleted.append(key)
        return deleted

    def _stored(self, key: _EvidenceMarkKey) -> FleetEvidenceMark:
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            loaded = self._read(key)
            raced = self._cache.get(key)
            if raced is not None:
                return raced
            self._cache[key] = loaded
            return loaded

    def _cached_or_read(self, key: _EvidenceMarkKey) -> FleetEvidenceMark:
        """The cached mark, else the stored document, without filling the cache."""
        with self._lock:
            current = self._cache.get(key)
            if current is None:
                current = self._read(key)
            return current

    def _read(self, key: _EvidenceMarkKey) -> FleetEvidenceMark:
        data = read_json_object(self._storage, self.key(*key))
        if data is None:
            return _ABSENT_EVIDENCE_MARK
        return fleet_evidence_mark_from_json(data)

    def _write(self, key: _EvidenceMarkKey, mark: FleetEvidenceMark) -> None:
        self._storage.put(self.key(*key), fleet_evidence_mark_to_json(mark))
