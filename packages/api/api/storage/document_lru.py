"""Process-wide bounded LRUs of file-backend breakpoint JSON and prefix listings.

Keyed by resolved ``storage_root`` so two ``FileStorageBackend`` instances on the
same root share hits, and distinct roots do not. Cached values stay ``JSONValue``;
this is not a ``TurnInfo`` cache.

Turn RST documents (``games/{game}/{perspective}/turns/{turn}``) and credentials
(``credentials/accounts/{id}``) are not retained. Analytic breakpoint documents,
including ``…/turns/{turn}/analytics/{id}``, are admitted.

Listings are a separate map of filesystem prefix to child names. Successful
put/delete of a document -- admitted or not -- drops ancestor prefix listings;
listings are never patched in place. A miss captures a mutation epoch; fill from
I/O installs only when that epoch is still current.
"""

from __future__ import annotations

import threading
from pathlib import Path

from api.lru_cache import LruCache
from api.storage.base import JSONValue
from api.storage.boundaries import _pattern_matches_path

# Hot set is current-turn analytic documents; a fleet document is large.
FILE_DOCUMENT_LRU_MAXSIZE = 16
FILE_LISTING_LRU_MAXSIZE = 32

_TURN_RST_PATTERN = ("games", "*", "*", "turns", "*")
_CREDENTIALS_PATTERN = ("credentials", "accounts", "*")

_registry_lock = threading.Lock()
_lrus_by_root: dict[str, FileBackendDocumentLru] = {}


def _path_segments(path: str) -> list[str]:
    return [segment for segment in path.strip("/").split("/") if segment]


def admits_breakpoint_document(breakpoint_path: str) -> bool:
    """Return whether the file backend may retain this breakpoint JSON tree."""
    segments = _path_segments(breakpoint_path)
    if _pattern_matches_path(_CREDENTIALS_PATTERN, segments):
        return False
    if _pattern_matches_path(_TURN_RST_PATTERN, segments):
        return False
    return True


def _root_key(storage_root: Path) -> str:
    return str(storage_root.expanduser().resolve())


def document_lru_for_root(storage_root: Path) -> FileBackendDocumentLru:
    """Return the process LRU for ``storage_root``, creating it if needed."""
    key = _root_key(storage_root)
    with _registry_lock:
        existing = _lrus_by_root.get(key)
        if existing is None:
            existing = FileBackendDocumentLru()
            _lrus_by_root[key] = existing
        return existing


def listing_prefixes_to_invalidate(breakpoint_path: str) -> tuple[str, ...]:
    """Ancestor filesystem prefixes of a breakpoint document, including root."""
    segments = _path_segments(breakpoint_path)
    prefixes = [""]
    for index in range(1, len(segments)):
        prefixes.append("/".join(segments[:index]))
    return tuple(prefixes)


class FileBackendDocumentLru:
    """Bounded document and listing maps for one resolved storage root."""

    def __init__(
        self,
        *,
        document_maxsize: int = FILE_DOCUMENT_LRU_MAXSIZE,
        listing_maxsize: int = FILE_LISTING_LRU_MAXSIZE,
    ) -> None:
        self._documents: LruCache[str, JSONValue] = LruCache(document_maxsize)
        self._listings: LruCache[str, tuple[str, ...]] = LruCache(listing_maxsize)
        self._epoch = 0
        self._lock = threading.Lock()

    def get_document(self, breakpoint_path: str) -> tuple[JSONValue | None, int]:
        """Return (retained tree or None, epoch). Fill from I/O only at this epoch."""
        if not admits_breakpoint_document(breakpoint_path):
            return None, 0
        with self._lock:
            return self._documents.get(breakpoint_path), self._epoch

    def remember_document(self, breakpoint_path: str, document: JSONValue) -> None:
        """Write-through after a successful disk put.

        Retains the tree only when the path is admitted. Always invalidates
        ancestor listings.
        """
        with self._lock:
            if admits_breakpoint_document(breakpoint_path):
                self._documents.put(breakpoint_path, document)
            self._record_mutation_locked(breakpoint_path)

    def fill_document(self, breakpoint_path: str, document: JSONValue, *, epoch: int) -> None:
        """Install a disk-loaded tree only when ``epoch`` is still current."""
        if not admits_breakpoint_document(breakpoint_path):
            return
        with self._lock:
            if epoch != self._epoch:
                return
            self._documents.put(breakpoint_path, document)

    def drop_document(self, breakpoint_path: str) -> None:
        """Forget a document after a successful disk delete or prune.

        Always invalidates ancestor listings, including when the path was not retained.
        """
        with self._lock:
            self._documents.drop(breakpoint_path)
            self._record_mutation_locked(breakpoint_path)

    def get_listing(self, prefix: str) -> tuple[tuple[str, ...] | None, int]:
        """Return (cached child names or None, epoch). Fill from I/O only at this epoch."""
        with self._lock:
            return self._listings.get(prefix), self._epoch

    def fill_listing(self, prefix: str, names: list[str], *, epoch: int) -> None:
        """Install a filesystem listing only when ``epoch`` is still current."""
        with self._lock:
            if epoch != self._epoch:
                return
            self._listings.put(prefix, tuple(names))

    def has_document(self, breakpoint_path: str) -> bool:
        """Return whether ``breakpoint_path`` is currently retained (tests)."""
        with self._lock:
            return breakpoint_path in self._documents

    def document_count(self) -> int:
        """Return the number of retained documents (tests)."""
        with self._lock:
            return len(self._documents)

    def _record_mutation_locked(self, breakpoint_path: str) -> None:
        self._epoch += 1
        for prefix in listing_prefixes_to_invalidate(breakpoint_path):
            self._listings.drop(prefix)
