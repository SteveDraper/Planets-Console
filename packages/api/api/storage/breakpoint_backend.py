"""Logical StorageBackend over one breakpoint document store."""

from __future__ import annotations

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import resolve_breakpoint
from api.storage.document_store import DocumentStore
from api.storage.documents import (
    document_after_delete,
    document_after_put,
    list_logical,
    read_logical,
)
from api.storage.migrations import DEFAULT_STORAGE_FORMAT, StorageFormat
from api.storage.path_utils import deep_copy_value, normalize_store_key


def resolve_storage_format(storage_format: StorageFormat | None) -> StorageFormat:
    """Return ``storage_format``, or the build default when it is omitted."""
    if storage_format is None:
        return DEFAULT_STORAGE_FORMAT
    return storage_format


class BreakpointDocumentBackend:
    """Logical JSON store over an already prepared breakpoint document store.

    A file directory is opened, or an ephemeral seed is partitioned and
    stamped, before this backend is constructed. ``get`` returns a deep copy.
    ``put`` and ``delete`` hold the store's ``document_lock`` for the whole
    read-modify-write of one breakpoint.
    """

    def __init__(
        self,
        document_store: DocumentStore,
        storage_format: StorageFormat | None = None,
    ) -> None:
        resolved_format = resolve_storage_format(storage_format)
        self._patterns = resolved_format.patterns
        self._document_store = document_store

    def get(self, key: str) -> JSONValue:
        path = normalize_store_key(key)
        if path == "":
            raise ValidationError("Cannot get root path")
        breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
        document = self._document_store.load_document(breakpoint_path)
        return read_logical(document, suffix)

    def put(self, key: str, value: JSONValue) -> None:
        path = normalize_store_key(key)
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
            missing = False
        except NotFoundError:
            current = None
            missing = True
        updated = document_after_put(
            current,
            suffix,
            value_copy,
            breakpoint_path=breakpoint_path,
            missing=missing,
        )
        self._document_store.replace_document(breakpoint_path, updated)

    def delete(self, key: str) -> None:
        path = normalize_store_key(key)
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
        path = normalize_store_key(prefix)
        return list_logical(
            path,
            patterns=self._patterns,
            document_exists=self._document_store.has_document,
            load_document=self._document_store.load_document,
            child_names=self._document_store.child_names,
        )
