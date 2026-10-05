"""In-memory StorageBackend.

Documents are keyed by breakpoint path, matching the file backend. A put of a
longer breakpoint does not nest inside the shorter document. ``initial`` is a
logical JSON tree in the current layout, including a ``storage_asset_path``
asset. It is partitioned with the current registry and stamped at the current
version. Migrations do not run over that seed. A tree that contains the
``meta`` namespace raises ``ValidationError``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue
from api.storage.breakpoint_backend import BreakpointDocumentBackend, resolve_storage_format
from api.storage.documents import child_names_for_prefix, partition_logical_tree
from api.storage.migrations import STORAGE_VERSION_KEY, StorageFormat, stamp_version
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


def _reject_seed_meta(root: dict[str, JSONValue]) -> None:
    """Raise when ``root`` contains the storage-meta namespace."""
    namespace = STORAGE_VERSION_KEY.split("/", 1)[0]
    if namespace in root:
        raise ValidationError(f"Seed must not contain the {namespace!r} namespace")


class MemoryAssetBackend(BreakpointDocumentBackend):
    """Storage backend that holds breakpoint documents in memory.

    ``initial`` is a current-layout logical tree. It is partitioned and stamped
    at the bound format's current version. The document map and its lock live
    on the composed ``MemoryDocumentStore``.
    """

    def __init__(
        self,
        initial: dict[str, JSONValue] | None = None,
        *,
        storage_format: StorageFormat | None = None,
    ) -> None:
        resolved_format = resolve_storage_format(storage_format)
        tree = {} if initial is None else initial
        _reject_seed_meta(tree)
        seeded = partition_logical_tree(tree, resolved_format.patterns)
        document_store = MemoryDocumentStore(seeded)
        stamp_version(document_store, resolved_format.current_version)
        super().__init__(document_store, resolved_format)
