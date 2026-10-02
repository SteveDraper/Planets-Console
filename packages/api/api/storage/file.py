"""Durable StorageBackend: JSON documents at registry breakpoints on disk."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from pathlib import Path

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import (
    BREAKPOINT_PATTERNS,
    BreakpointPatterns,
    document_relpath,
    resolve_breakpoint,
)
from api.storage.document_lru import document_lru_for_root
from api.storage.documents import (
    document_after_delete,
    document_after_put,
    list_logical,
    read_logical,
)
from api.storage.migrations import (
    CURRENT_STORAGE_VERSION,
    MINIMUM_STORAGE_VERSION,
    StorageMigration,
    open_store,
    production_migrations,
    superseded_layout_error,
)
from api.storage.path_utils import deep_copy_value, validate_no_reserved_at_keys


class FileStorageBackend:
    """Persist the logical JSON store as breakpoint JSON files under ``storage_root``.

    Admitted breakpoint documents (not turn RST, not credentials) are retained in
    a process-wide LRU keyed by resolved root. Successful put/delete invalidates
    ancestor listings even when the document is not retained. ``get`` returns a
    deep copy.
    """

    def __init__(
        self,
        storage_root: Path,
        *,
        patterns: BreakpointPatterns | None = None,
        migrations: tuple[StorageMigration, ...] | None = None,
        current_version: int | None = None,
        minimum_version: int | None = None,
    ) -> None:
        self._root = storage_root
        self._patterns = BREAKPOINT_PATTERNS if patterns is None else patterns
        self._migrations = production_migrations() if migrations is None else migrations
        self._current_version = (
            CURRENT_STORAGE_VERSION if current_version is None else current_version
        )
        self._minimum_version = (
            MINIMUM_STORAGE_VERSION if minimum_version is None else minimum_version
        )
        self._document_lru = document_lru_for_root(storage_root)
        open_store(
            self,
            patterns=self._patterns,
            migrations=self._migrations,
            current_version=self._current_version,
            minimum_version=self._minimum_version,
        )

    def _normalize(self, key: str) -> str:
        return (key or "").strip().strip("/") or ""

    def _document_file(self, breakpoint_path: str) -> Path:
        return self._root / document_relpath(breakpoint_path)

    def _load_document(self, breakpoint_path: str) -> JSONValue:
        cached, epoch = self._document_lru.get_document(breakpoint_path)
        if cached is not None:
            return cached
        file_path = self._document_file(breakpoint_path)
        try:
            with open(file_path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except FileNotFoundError:
            # Concurrent delete/prune can unlink between a peer's write and this
            # open (same race as ``_ensure_dir`` after a persistence clear).
            raise NotFoundError(f"Document not found: {breakpoint_path!r}") from None
        self._document_lru.fill_document(breakpoint_path, loaded, epoch=epoch)
        return loaded

    @staticmethod
    def _ensure_dir(path: Path, *, attempts: int = 8) -> None:
        """Create ``path`` as a directory, tolerating concurrent creators/pruners.

        ``Path.mkdir(parents=True, exist_ok=True)`` can still raise
        ``FileExistsError`` under TOCTOU: another thread creates the dir (mkdir
        raises EEXIST), then a pruner deletes it before ``is_dir()`` runs, so
        CPython re-raises. Concurrent fleet/scores analytic puts after a clear
        hit this on ``…/turns/N/analytics``. Retry while the path is absent or
        already a directory; only fail when a non-directory occupies the path.
        """
        last_error: FileExistsError | None = None
        for _ in range(attempts):
            try:
                path.mkdir(parents=True, exist_ok=True)
                return
            except FileExistsError as exc:
                last_error = exc
                if path.is_dir():
                    return
                if path.exists():
                    raise
        if last_error is not None:
            raise last_error
        path.mkdir(parents=True, exist_ok=True)

    def _write_replaced(self, file_path: Path, value: JSONValue) -> None:
        self._ensure_dir(file_path.parent)
        temp_path = file_path.with_name(
            f".{file_path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False)
                handle.write("\n")
            os.replace(temp_path, file_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _atomic_write(self, file_path: Path, value: JSONValue, *, attempts: int = 8) -> None:
        """Write ``value`` via temp + replace, retrying when a peer prunes the parent.

        After a persistence clear, concurrent fleet/scores puts share
        ``…/turns/N/analytics``. A pruner can remove that directory after
        ``_ensure_dir`` and before ``open`` / ``os.replace``, which raises
        ``FileNotFoundError`` with the destination path (e.g. ``fleet.json``).
        """
        validate_no_reserved_at_keys(value)
        for attempt in range(attempts):
            try:
                self._write_replaced(file_path, value)
                return
            except FileNotFoundError:
                if attempt + 1 >= attempts:
                    relative_path = file_path.relative_to(self._root).as_posix()
                    raise NotFoundError(f"Document not found: {relative_path!r}") from None

    def _prune_empty_dirs(self, start: Path) -> None:
        current = start
        while current != self._root and current.is_dir():
            try:
                next(current.iterdir())
            except FileNotFoundError:
                break
            except StopIteration:
                try:
                    current.rmdir()
                except FileNotFoundError:
                    # Concurrent prune or recreate removed this directory.
                    break
                except OSError:
                    # Concurrent put populated the directory after our empty check.
                    break
                current = current.parent
            else:
                break

    def _delete_document(self, breakpoint_path: str) -> None:
        file_path = self._document_file(breakpoint_path)
        try:
            file_path.unlink()
        except FileNotFoundError:
            raise NotFoundError(f"Document not found: {breakpoint_path!r}") from None
        self._document_lru.drop_document(breakpoint_path)
        self._prune_empty_dirs(file_path.parent)

    def _list_filesystem_prefix(self, prefix: str) -> list[str]:
        cached, epoch = self._document_lru.get_listing(prefix)
        if cached is not None:
            return list(cached)
        dir_path = self._root if prefix == "" else self._root / prefix
        if not dir_path.is_dir():
            raise NotFoundError(f"Path does not exist: {prefix!r}")
        try:
            entries = tuple(dir_path.iterdir())
        except FileNotFoundError:
            raise NotFoundError(f"Path does not exist: {prefix!r}") from None
        names: list[str] = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                names.append(entry.name)
            elif entry.is_file() and entry.suffix == ".json":
                names.append(entry.stem)
        names = sorted(names)
        self._document_lru.fill_listing(prefix, names, epoch=epoch)
        return names

    def iter_document_paths(self) -> Iterator[str]:
        if not self._root.is_dir():
            return
        for file_path in self._root.rglob("*.json"):
            if file_path.name.startswith("."):
                continue
            relative = file_path.relative_to(self._root).as_posix()
            if relative.endswith(".json"):
                yield relative[: -len(".json")]

    def has_document(self, breakpoint_path: str) -> bool:
        return self._document_file(breakpoint_path).is_file()

    def read_document(self, breakpoint_path: str) -> JSONValue:
        return self._load_document(breakpoint_path)

    def write_document(self, breakpoint_path: str, value: JSONValue) -> None:
        stored = deep_copy_value(value)
        self._atomic_write(self._document_file(breakpoint_path), stored)
        self._document_lru.remember_document(breakpoint_path, stored)

    def remove_document(self, breakpoint_path: str) -> None:
        self._delete_document(breakpoint_path)

    def get(self, key: str) -> JSONValue:
        path = self._normalize(key)
        if path == "":
            raise ValidationError("Cannot get root path")
        breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
        try:
            document = self._load_document(breakpoint_path)
        except NotFoundError:
            superseded = superseded_layout_error(
                self,
                path,
                patterns=self._patterns,
                migrations=self._migrations,
            )
            if superseded is not None:
                raise superseded from None
            raise
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
        with self._document_lru.document_lock(breakpoint_path):
            self._put_document(breakpoint_path, suffix, value_copy)

    def _put_document(
        self,
        breakpoint_path: str,
        suffix: str | None,
        value_copy: JSONValue,
    ) -> None:
        file_path = self._document_file(breakpoint_path)

        if suffix is None:
            self._atomic_write(file_path, value_copy)
            self._document_lru.remember_document(breakpoint_path, value_copy)
            return

        try:
            current = self._load_document(breakpoint_path)
        except NotFoundError:
            current = None
        updated = document_after_put(
            current,
            suffix,
            value_copy,
            breakpoint_path=breakpoint_path,
        )
        self._atomic_write(file_path, updated)
        self._document_lru.remember_document(breakpoint_path, updated)

    def delete(self, key: str) -> None:
        path = self._normalize(key)
        if path == "":
            raise ValidationError("Cannot delete root path")
        breakpoint_path, suffix = resolve_breakpoint(path, self._patterns)
        with self._document_lru.document_lock(breakpoint_path):
            if suffix is None:
                self._delete_document(breakpoint_path)
                return

            document = self._load_document(breakpoint_path)
            updated = document_after_delete(document, suffix)
            self._atomic_write(self._document_file(breakpoint_path), updated)
            self._document_lru.remember_document(breakpoint_path, updated)

    def list(self, prefix: str) -> list[str]:
        # Intermediate prefixes between breakpoints (for example
        # .../turns/N/analytics) list sibling documents, not a key inside the
        # shorter document. An exact breakpoint that is also the directory of a
        # longer one lists that directory when the shared file is absent.
        path = self._normalize(prefix)
        return list_logical(
            path,
            patterns=self._patterns,
            document_exists=self.has_document,
            load_document=self._load_document,
            child_names=self._child_names,
        )

    def _child_names(self, prefix: str) -> list[str]:
        if prefix == "" and not self._root.is_dir():
            return []
        return self._list_filesystem_prefix(prefix)
