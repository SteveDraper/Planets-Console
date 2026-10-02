"""In-memory StorageBackend.

Documents are keyed by breakpoint path, matching the file backend. A put of a
longer breakpoint does not nest inside the shorter document. An optional
``initial`` tree is partitioned into those documents on open. ``documents``
seeds the breakpoint map directly so a test can open an older layout.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import BREAKPOINT_PATTERNS, BreakpointPatterns, resolve_breakpoint
from api.storage.documents import (
    child_names_for_prefix,
    document_after_delete,
    document_after_put,
    list_logical,
    partition_logical_tree,
    read_logical,
)
from api.storage.migrations import (
    CURRENT_STORAGE_VERSION,
    MINIMUM_STORAGE_VERSION,
    StorageMigration,
    open_store,
    superseded_layout_error,
)
from api.storage.path_utils import deep_copy_value, validate_no_reserved_at_keys


class MemoryAssetBackend:
    """Storage backend that holds breakpoint documents in memory."""

    def __init__(
        self,
        initial: dict[str, JSONValue] | None = None,
        *,
        documents: dict[str, JSONValue] | None = None,
        patterns: BreakpointPatterns | None = None,
        migrations: tuple[StorageMigration, ...] = (),
        current_version: int | None = None,
        minimum_version: int | None = None,
    ) -> None:
        if documents is not None and initial is not None:
            raise ValueError("pass initial or documents, not both")
        self._lock = threading.RLock()
        self._patterns = BREAKPOINT_PATTERNS if patterns is None else patterns
        self._migrations = migrations
        self._current_version = (
            CURRENT_STORAGE_VERSION if current_version is None else current_version
        )
        self._minimum_version = (
            MINIMUM_STORAGE_VERSION if minimum_version is None else minimum_version
        )
        if documents is not None:
            self._documents = {path: deep_copy_value(value) for path, value in documents.items()}
        else:
            self._documents = partition_logical_tree(initial or {}, self._patterns)
        open_store(
            self,
            patterns=self._patterns,
            migrations=self._migrations,
            current_version=self._current_version,
            minimum_version=self._minimum_version,
        )

    def iter_document_paths(self) -> Iterator[str]:
        with self._lock:
            paths = tuple(self._documents)
        yield from paths

    def has_document(self, breakpoint_path: str) -> bool:
        with self._lock:
            return breakpoint_path in self._documents

    def read_document(self, breakpoint_path: str) -> JSONValue:
        with self._lock:
            try:
                return self._documents[breakpoint_path]
            except KeyError:
                raise NotFoundError(f"Document not found: {breakpoint_path!r}") from None

    def write_document(self, breakpoint_path: str, value: JSONValue) -> None:
        validate_no_reserved_at_keys(value)
        stored = deep_copy_value(value)
        with self._lock:
            self._documents[breakpoint_path] = stored

    def remove_document(self, breakpoint_path: str) -> None:
        with self._lock:
            try:
                del self._documents[breakpoint_path]
            except KeyError:
                raise NotFoundError(f"Document not found: {breakpoint_path!r}") from None

    def get(self, key: str) -> JSONValue:
        """Return a deep copy of the value at path. Raises NotFoundError if path does not exist."""
        with self._lock:
            path = _normalize(key)
            if path == "":
                raise ValidationError("Cannot get root path")
            breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
            document = self._documents.get(breakpoint_path)
            if document is None:
                superseded = superseded_layout_error(
                    self,
                    path,
                    patterns=self._patterns,
                    migrations=self._migrations,
                )
                if superseded is not None:
                    raise superseded
                raise NotFoundError(f"Document not found: {breakpoint_path!r}")
            return read_logical(document, suffix)

    def put(self, key: str, value: JSONValue) -> None:
        """Store value at path. Creates the breakpoint document if needed."""
        with self._lock:
            path = _normalize(key)
            if path == "":
                raise ValidationError("Cannot put root path")
            breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
            validate_no_reserved_at_keys(value)
            value_copy = deep_copy_value(value)
            updated = document_after_put(
                self._documents.get(breakpoint_path),
                suffix,
                value_copy,
                breakpoint_path=breakpoint_path,
            )
            self._documents[breakpoint_path] = updated

    def delete(self, key: str) -> None:
        """Remove the node at path. Raises NotFoundError if path does not exist."""
        with self._lock:
            path = _normalize(key)
            if path == "":
                raise ValidationError("Cannot delete root path")
            breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
            document = self._documents.get(breakpoint_path)
            if document is None:
                raise NotFoundError(f"Document not found: {breakpoint_path!r}")
            if suffix is None:
                del self._documents[breakpoint_path]
                return
            self._documents[breakpoint_path] = document_after_delete(document, suffix)

    def list(self, prefix: str) -> list[str]:
        """Return next-hop segment names under the prefix."""
        with self._lock:
            path = _normalize(prefix)

            def child_names(prefix_path: str) -> list[str]:
                return child_names_for_prefix(self._documents, prefix_path)

            return list_logical(
                path,
                patterns=self._patterns,
                document_exists=lambda breakpoint_path: breakpoint_path in self._documents,
                load_document=lambda breakpoint_path: self._documents[breakpoint_path],
                child_names=child_names,
            )


def _normalize(key: str) -> str:
    return (key or "").strip().strip("/") or ""
