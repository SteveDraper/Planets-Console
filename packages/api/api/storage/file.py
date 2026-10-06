"""Durable StorageBackend: JSON documents at registry breakpoints on disk."""

from __future__ import annotations

from pathlib import Path

from api.storage.breakpoint_backend import BreakpointDocumentBackend, resolve_storage_format
from api.storage.document_lru import DocumentCacheCaps
from api.storage.file_documents import FileDocumentStore
from api.storage.migrations import StorageFormat, open_store


class FileStorageBackend(BreakpointDocumentBackend):
    """Persist the logical JSON store as breakpoint JSON files under ``storage_root``.

    Admitted breakpoint documents (not turn RST, not credentials) are retained
    in process-wide small and large LRUs keyed by resolved root. File byte size
    at put and fill selects the cache. ``cache_caps`` is required and is not
    defaulted here. A later backend on the same resolved root must pass equal
    caps. Successful put/delete invalidates ancestor listings even when the
    document is not retained. ``get`` returns a deep copy. Breakpoint file I/O
    lives on the composed ``FileDocumentStore``. The directory is opened before
    logical reads and writes.
    """

    def __init__(
        self,
        storage_root: Path,
        *,
        cache_caps: DocumentCacheCaps,
        storage_format: StorageFormat | None = None,
    ) -> None:
        document_store = FileDocumentStore(storage_root, cache_caps=cache_caps)
        resolved_format = resolve_storage_format(storage_format)
        open_store(document_store, resolved_format)
        super().__init__(document_store, resolved_format)
