"""Durable StorageBackend: JSON documents at registry breakpoints on disk."""

from __future__ import annotations

from pathlib import Path

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import (
    BREAKPOINT_PATTERNS,
    BreakpointPatterns,
    resolve_breakpoint,
)
from api.storage.documents import (
    document_after_delete,
    document_after_put,
    list_logical,
    read_logical,
)
from api.storage.file_documents import FileDocumentStore
from api.storage.migrations import (
    CURRENT_STORAGE_VERSION,
    MINIMUM_STORAGE_VERSION,
    StorageMigration,
    open_store,
)
from api.storage.path_utils import deep_copy_value


class FileStorageBackend:
    """Persist the logical JSON store as breakpoint JSON files under ``storage_root``.

    Admitted breakpoint documents (not turn RST, not credentials) are retained in
    a process-wide LRU keyed by resolved root. Successful put/delete invalidates
    ancestor listings even when the document is not retained. ``get`` returns a
    deep copy. Breakpoint file I/O lives on the composed ``FileDocumentStore``.
    """

    def __init__(
        self,
        storage_root: Path,
        *,
        patterns: BreakpointPatterns | None = None,
        migrations: tuple[StorageMigration, ...] = (),
        current_version: int | None = None,
        minimum_version: int | None = None,
    ) -> None:
        self._patterns = BREAKPOINT_PATTERNS if patterns is None else patterns
        self._migrations = migrations
        self._current_version = (
            CURRENT_STORAGE_VERSION if current_version is None else current_version
        )
        self._minimum_version = (
            MINIMUM_STORAGE_VERSION if minimum_version is None else minimum_version
        )
        self._document_store = FileDocumentStore(storage_root)
        open_store(
            self._document_store,
            patterns=self._patterns,
            migrations=self._migrations,
            current_version=self._current_version,
            minimum_version=self._minimum_version,
        )

    def _normalize(self, key: str) -> str:
        return (key or "").strip().strip("/") or ""

    def get(self, key: str) -> JSONValue:
        path = self._normalize(key)
        if path == "":
            raise ValidationError("Cannot get root path")
        breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
        document = self._document_store.load_document(breakpoint_path)
        return read_logical(document, suffix)

    def put(self, key: str, value: JSONValue) -> None:
        path = self._normalize(key)
        if path == "":
            raise ValidationError("Cannot put root path")
        breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
        value_copy = deep_copy_value(value)
        # Nested keys of one breakpoint share a JSON document. Concurrent
        # read-modify-write otherwise drops sibling keys (scores inference rows
        # during map ensure).
        with self._document_store.document_lock(breakpoint_path):
            self._put_document(breakpoint_path, suffix, value_copy)

    def _put_document(
        self,
        breakpoint_path: str,
        suffix: str | None,
        value_copy: JSONValue,
    ) -> None:
        if suffix is None:
            self._document_store.replace_document(breakpoint_path, value_copy)
            return

        try:
            current = self._document_store.load_document(breakpoint_path)
        except NotFoundError:
            current = None
        updated = document_after_put(
            current,
            suffix,
            value_copy,
            breakpoint_path=breakpoint_path,
        )
        self._document_store.replace_document(breakpoint_path, updated)

    def delete(self, key: str) -> None:
        path = self._normalize(key)
        if path == "":
            raise ValidationError("Cannot delete root path")
        breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
        with self._document_store.document_lock(breakpoint_path):
            if suffix is None:
                self._document_store.remove_document(breakpoint_path)
                return

            document = self._document_store.load_document(breakpoint_path)
            updated = document_after_delete(document, suffix)
            self._document_store.replace_document(breakpoint_path, updated)

    def list(self, prefix: str) -> list[str]:
        # Intermediate prefixes between breakpoints (for example
        # .../turns/N/analytics) list sibling documents, not a key inside the
        # shorter document. An exact breakpoint that is also the directory of a
        # longer one lists that directory when the shared file is absent.
        path = self._normalize(prefix)
        return list_logical(
            path,
            patterns=self._patterns,
            document_exists=self._document_store.has_document,
            load_document=self._document_store.load_document,
            child_names=self._document_store.child_names,
        )
