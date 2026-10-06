"""Process-wide bounded LRUs of file-backend breakpoint JSON and prefix listings.

Keyed by resolved ``storage_root`` so two ``FileStorageBackend`` instances on the
same root share hits, and distinct roots do not. Cached values stay ``JSONValue``;
this is not a ``TurnInfo`` cache.

Turn RST documents (``games/{game}/{perspective}/turns/{turn}``) and credentials
(``credentials/accounts/{id}``) are not retained. Analytic breakpoint documents,
including ``…/turns/{turn}/analytics/{id}``, are admitted.

Admitted documents are split by file byte size at insert. Documents under
128 KB use the small-document cache. Documents of 128 KB and above use the
large-document cache. A later put that crosses the threshold moves the entry.
``get`` finds the document in whichever cache holds it. Openers pass
``DocumentCacheCaps``. This module does not read process config, and the
cache type does not default either cap. A later opener of the same resolved
root with different caps raises ``ConflictError``.

Listings are a separate map of filesystem prefix to child names. Successful
put/delete of a document -- admitted or not -- drops ancestor prefix listings;
listings are never patched in place. A miss captures a mutation epoch; fill from
I/O installs only when that epoch is still current.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from api.errors import ConflictError
from api.lru_cache import LruCache
from api.storage.base import JSONValue
from api.storage.boundaries import _pattern_matches_path

# File byte size at remember / fill. Under this is the small-document cache.
LARGE_DOCUMENT_MIN_BYTES = 128 * 1024
FILE_LISTING_LRU_MAXSIZE = 32

_TURN_RST_PATTERN = ("games", "*", "*", "turns", "*")
_CREDENTIALS_PATTERN = ("credentials", "accounts", "*")

_registry_lock = threading.Lock()
_lrus_by_root: dict[str, FileBackendDocumentLru] = {}


@dataclass(frozen=True)
class DocumentCacheCaps:
    """Entry caps for one root's small-document and large-document caches.

    Both sizes are required. This type does not default either cap.
    """

    small_document_maxsize: int
    large_document_maxsize: int


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


def document_lru_for_root(
    storage_root: Path,
    cache_caps: DocumentCacheCaps,
) -> FileBackendDocumentLru:
    """Return the process LRU for ``storage_root``, creating it when absent.

    The first caller for a resolved root constructs the cache with ``cache_caps``.
    A later caller with equal caps receives that cache. Different caps raise
    ``ConflictError``.
    """
    key = _root_key(storage_root)
    with _registry_lock:
        existing = _lrus_by_root.get(key)
        if existing is None:
            created = FileBackendDocumentLru(
                small_document_maxsize=cache_caps.small_document_maxsize,
                large_document_maxsize=cache_caps.large_document_maxsize,
            )
            _lrus_by_root[key] = created
            return created
        if (
            existing._small_document_maxsize != cache_caps.small_document_maxsize
            or existing._large_document_maxsize != cache_caps.large_document_maxsize
        ):
            raise ConflictError(
                f"Document cache caps for storage root {key} are already "
                f"small={existing._small_document_maxsize} "
                f"large={existing._large_document_maxsize}; "
                "this opener requested "
                f"small={cache_caps.small_document_maxsize} "
                f"large={cache_caps.large_document_maxsize}"
            )
        return existing


def listing_prefixes_to_invalidate(breakpoint_path: str) -> tuple[str, ...]:
    """Ancestor filesystem prefixes of a breakpoint document, including root."""
    segments = _path_segments(breakpoint_path)
    prefixes = [""]
    for index in range(1, len(segments)):
        prefixes.append("/".join(segments[:index]))
    return tuple(prefixes)


class FileBackendDocumentLru:
    """Bounded document and listing maps for one resolved storage root.

    ``small_document_maxsize`` and ``large_document_maxsize`` are required.
    This type does not default either cap.
    """

    def __init__(
        self,
        *,
        small_document_maxsize: int,
        large_document_maxsize: int,
        listing_maxsize: int = FILE_LISTING_LRU_MAXSIZE,
    ) -> None:
        self._small_document_maxsize = small_document_maxsize
        self._large_document_maxsize = large_document_maxsize
        self._small_documents: LruCache[str, JSONValue] = LruCache(small_document_maxsize)
        self._large_documents: LruCache[str, JSONValue] = LruCache(large_document_maxsize)
        self._listings: LruCache[str, tuple[str, ...]] = LruCache(listing_maxsize)
        self._epoch = 0
        self._lock = threading.Lock()
        # One lock per breakpoint so nested puts of the same document cannot
        # replace each other from a stale copy. Shared with every backend on
        # this root, same as the document map.
        self._mutation_locks: dict[str, threading.Lock] = {}

    def small_document_maxsize(self) -> int:
        """Return the small-document entry cap (tests and startup checks)."""
        return self._small_document_maxsize

    def large_document_maxsize(self) -> int:
        """Return the large-document entry cap (tests and startup checks)."""
        return self._large_document_maxsize

    def document_lock(self, breakpoint_path: str) -> threading.Lock:
        """Return the mutation lock for one breakpoint document.

        Callers hold it across a nested read-modify-write. Distinct breakpoint
        paths do not share a lock. Never acquire this while holding ``_lock``.
        """
        with self._lock:
            lock = self._mutation_locks.get(breakpoint_path)
            if lock is None:
                lock = threading.Lock()
                self._mutation_locks[breakpoint_path] = lock
            return lock

    def get_document(self, breakpoint_path: str) -> tuple[JSONValue | None, int]:
        """Return (retained tree or None, epoch). Fill from I/O only at this epoch."""
        if not admits_breakpoint_document(breakpoint_path):
            return None, 0
        with self._lock:
            retained = self._small_documents.get(breakpoint_path)
            if retained is None:
                retained = self._large_documents.get(breakpoint_path)
            return retained, self._epoch

    def remember_document(
        self,
        breakpoint_path: str,
        document: JSONValue,
        *,
        byte_size: int,
    ) -> None:
        """Write-through after a successful disk put.

        ``byte_size`` is the file's byte size. Retains the tree only when the
        path is admitted, on the cache that size selects. Always invalidates
        ancestor listings.
        """
        with self._lock:
            if admits_breakpoint_document(breakpoint_path):
                self._retain_locked(breakpoint_path, document, byte_size)
            self._record_mutation_locked(breakpoint_path)

    def fill_document(
        self,
        breakpoint_path: str,
        document: JSONValue,
        *,
        epoch: int,
        byte_size: int,
    ) -> None:
        """Install a disk-loaded tree only when ``epoch`` is still current.

        ``byte_size`` is the file's byte size and selects the cache.
        """
        if not admits_breakpoint_document(breakpoint_path):
            return
        with self._lock:
            if epoch != self._epoch:
                return
            self._retain_locked(breakpoint_path, document, byte_size)

    def drop_document(self, breakpoint_path: str) -> None:
        """Forget a document after a successful disk delete or prune.

        Always invalidates ancestor listings, including when the path was not retained.
        """
        with self._lock:
            self._small_documents.drop(breakpoint_path)
            self._large_documents.drop(breakpoint_path)
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
            return self._has_document_locked(breakpoint_path)

    def has_small_document(self, breakpoint_path: str) -> bool:
        """Return whether the small-document cache holds ``breakpoint_path`` (tests)."""
        with self._lock:
            return breakpoint_path in self._small_documents

    def has_large_document(self, breakpoint_path: str) -> bool:
        """Return whether the large-document cache holds ``breakpoint_path`` (tests)."""
        with self._lock:
            return breakpoint_path in self._large_documents

    def document_count(self) -> int:
        """Return the number of retained documents (tests)."""
        with self._lock:
            return len(self._small_documents) + len(self._large_documents)

    def small_document_count(self) -> int:
        """Return how many documents the small-document cache holds (tests)."""
        with self._lock:
            return len(self._small_documents)

    def large_document_count(self) -> int:
        """Return how many documents the large-document cache holds (tests)."""
        with self._lock:
            return len(self._large_documents)

    def _retain_locked(
        self,
        breakpoint_path: str,
        document: JSONValue,
        byte_size: int,
    ) -> None:
        """Store ``document`` on the cache ``byte_size`` selects, dropping the other."""
        if byte_size < LARGE_DOCUMENT_MIN_BYTES:
            selected = self._small_documents
            other = self._large_documents
        else:
            selected = self._large_documents
            other = self._small_documents
        other.drop(breakpoint_path)
        selected.put(breakpoint_path, document)

    def _has_document_locked(self, breakpoint_path: str) -> bool:
        return breakpoint_path in self._small_documents or breakpoint_path in self._large_documents

    def _record_mutation_locked(self, breakpoint_path: str) -> None:
        self._epoch += 1
        for prefix in listing_prefixes_to_invalidate(breakpoint_path):
            self._listings.drop(prefix)
