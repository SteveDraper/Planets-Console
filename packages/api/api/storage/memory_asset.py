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

from api.errors import NotFoundError
from api.storage.base import JSONValue
from api.storage.breakpoint_backend import BreakpointDocumentBackend, resolve_storage_format
from api.storage.documents import child_names_for_prefix, partition_logical_tree
from api.storage.migrations import StorageFormat
from api.storage.path_utils import deep_copy_value, validate_no_reserved_at_keys


class MemoryDocumentStore:
    """In-memory breakpoint documents.

    Owns the document map and its lock. ``read_document`` returns a copy.
    Logical updates take ``document_lock`` for the whole read-modify-write;
    store methods re-enter that lock. ``replace_document`` rejects reserved
    ``@`` object keys.
    """

    def __init__(self, documents: dict[str, JSONValue]) -> None:
        self._lock = threading.RLock()
        self._documents = documents

    @contextmanager
    def document_lock(self, breakpoint_path: str) -> Iterator[None]:
        """Hold the document map lock for one logical read-modify-write.

        One lock covers every breakpoint, including ``breakpoint_path``.
        """
        with self._lock:
            yield

    def iter_document_paths(self) -> Iterator[str]:
        with self._lock:
            paths = tuple(self._documents)
        yield from paths

    def has_document(self, breakpoint_path: str) -> bool:
        with self._lock:
            return breakpoint_path in self._documents

    def load_document(self, breakpoint_path: str) -> JSONValue:
        """Return the stored object. Do not mutate the result."""
        with self._lock:
            return self._stored(breakpoint_path)

    def read_document(self, breakpoint_path: str) -> JSONValue:
        with self._lock:
            return deep_copy_value(self._stored(breakpoint_path))

    def replace_document(self, breakpoint_path: str, value: JSONValue) -> None:
        """Store ``value`` as this breakpoint document."""
        validate_no_reserved_at_keys(value)
        with self._lock:
            self._documents[breakpoint_path] = value

    def write_document(self, breakpoint_path: str, value: JSONValue) -> None:
        self.replace_document(breakpoint_path, deep_copy_value(value))

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


class MemoryAssetBackend(BreakpointDocumentBackend):
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
        resolved_format = resolve_storage_format(storage_format)
        if documents is not None:
            seeded = {path: deep_copy_value(value) for path, value in documents.items()}
        else:
            seeded = partition_logical_tree(initial or {}, resolved_format.patterns)
        super().__init__(MemoryDocumentStore(seeded), resolved_format)
