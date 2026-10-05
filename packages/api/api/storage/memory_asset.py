"""In-memory StorageBackend.

Documents are keyed by breakpoint path, matching the file backend. A put of a
longer breakpoint does not nest inside the shorter document. An optional
``initial`` tree is partitioned into those documents on open. ``documents``
seeds the breakpoint map directly so a test can open an older layout.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import resolve_breakpoint
from api.storage.documents import (
    child_names_for_prefix,
    document_after_delete,
    document_after_put,
    list_logical,
    partition_logical_tree,
    read_logical,
)
from api.storage.migrations import DEFAULT_STORAGE_FORMAT, StorageFormat, open_store
from api.storage.path_utils import deep_copy_value, validate_no_reserved_at_keys


class MemoryDocumentStore:
    """In-memory breakpoint documents.

    Owns the document map and its lock. ``read_document`` returns a copy.
    Logical updates take ``hold`` for the whole read-modify-write; store
    methods re-enter that lock.
    """

    def __init__(self, documents: dict[str, JSONValue]) -> None:
        self._lock = threading.RLock()
        self._documents = documents

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Hold the document map lock for one logical read-modify-write."""
        with self._lock:
            yield

    def iter_document_paths(self) -> Iterator[str]:
        with self._lock:
            paths = tuple(self._documents)
        yield from paths

    def has_document(self, breakpoint_path: str) -> bool:
        with self._lock:
            return breakpoint_path in self._documents

    def get_document(self, breakpoint_path: str) -> JSONValue | None:
        """Return the stored object, or None when the breakpoint is absent."""
        with self._lock:
            return self._documents.get(breakpoint_path)

    def load_document(self, breakpoint_path: str) -> JSONValue:
        """Return the stored object. Do not mutate the result."""
        with self._lock:
            return self._stored(breakpoint_path)

    def read_document(self, breakpoint_path: str) -> JSONValue:
        with self._lock:
            return deep_copy_value(self._stored(breakpoint_path))

    def replace_document(self, breakpoint_path: str, value: JSONValue) -> None:
        """Store ``value`` as this breakpoint document."""
        with self._lock:
            self._documents[breakpoint_path] = value

    def write_document(self, breakpoint_path: str, value: JSONValue) -> None:
        validate_no_reserved_at_keys(value)
        stored = deep_copy_value(value)
        self.replace_document(breakpoint_path, stored)

    def remove_document(self, breakpoint_path: str) -> None:
        with self._lock:
            try:
                del self._documents[breakpoint_path]
            except KeyError:
                raise NotFoundError(f"Document not found: {breakpoint_path!r}") from None

    def child_names(self, prefix: str) -> list[str]:
        with self._lock:
            return child_names_for_prefix(self._documents, prefix)

    def _stored(self, breakpoint_path: str) -> JSONValue:
        """Return the stored object. Caller holds ``_lock``."""
        try:
            return self._documents[breakpoint_path]
        except KeyError:
            raise NotFoundError(f"Document not found: {breakpoint_path!r}") from None


class MemoryAssetBackend:
    """Storage backend that holds breakpoint documents in memory.

    The document map and its lock live on the composed ``MemoryDocumentStore``.
    """

    def __init__(
        self,
        initial: dict[str, JSONValue] | None = None,
        *,
        documents: dict[str, JSONValue] | None = None,
        storage_format: StorageFormat | None = None,
    ) -> None:
        if documents is not None and initial is not None:
            raise ValueError("pass initial or documents, not both")
        resolved_format = DEFAULT_STORAGE_FORMAT if storage_format is None else storage_format
        self._patterns = resolved_format.patterns
        if documents is not None:
            seeded = {path: deep_copy_value(value) for path, value in documents.items()}
        else:
            seeded = partition_logical_tree(initial or {}, self._patterns)
        self._document_store = MemoryDocumentStore(seeded)
        open_store(self._document_store, resolved_format)

    def get(self, key: str) -> JSONValue:
        """Return a deep copy of the value at path. Raises NotFoundError if path does not exist."""
        with self._document_store.hold():
            path = _normalize(key)
            if path == "":
                raise ValidationError("Cannot get root path")
            breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
            document = self._document_store.get_document(breakpoint_path)
            if document is None:
                raise NotFoundError(f"Document not found: {breakpoint_path!r}")
            return read_logical(document, suffix)

    def put(self, key: str, value: JSONValue) -> None:
        """Store value at path. Creates the breakpoint document if needed."""
        with self._document_store.hold():
            path = _normalize(key)
            if path == "":
                raise ValidationError("Cannot put root path")
            breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
            validate_no_reserved_at_keys(value)
            value_copy = deep_copy_value(value)
            updated = document_after_put(
                self._document_store.get_document(breakpoint_path),
                suffix,
                value_copy,
                breakpoint_path=breakpoint_path,
            )
            self._document_store.replace_document(breakpoint_path, updated)

    def delete(self, key: str) -> None:
        """Remove the node at path. Raises NotFoundError if path does not exist."""
        with self._document_store.hold():
            path = _normalize(key)
            if path == "":
                raise ValidationError("Cannot delete root path")
            breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
            document = self._document_store.get_document(breakpoint_path)
            if document is None:
                raise NotFoundError(f"Document not found: {breakpoint_path!r}")
            if suffix is None:
                self._document_store.remove_document(breakpoint_path)
                return
            self._document_store.replace_document(
                breakpoint_path,
                document_after_delete(document, suffix),
            )

    def list(self, prefix: str) -> list[str]:
        """Return next-hop segment names under the prefix."""
        with self._document_store.hold():
            path = _normalize(prefix)
            return list_logical(
                path,
                patterns=self._patterns,
                document_exists=self._document_store.has_document,
                load_document=self._document_store.load_document,
                child_names=self._document_store.child_names,
            )


def _normalize(key: str) -> str:
    return (key or "").strip().strip("/") or ""
