"""Breakpoint JSON files for one storage root.

``FileStorageBackend`` opens this store. Migrations use it as a ``DocumentStore``.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from api.errors import NotFoundError
from api.storage.base import JSONValue
from api.storage.boundaries import document_relpath
from api.storage.document_lru import DocumentCacheCaps, document_lru_for_root
from api.storage.path_utils import deep_copy_value, validate_no_reserved_at_keys


class FileDocumentStore:
    """Breakpoint JSON files under one storage root.

    Owns atomic replace, delete and prune, directory listing, and the process
    LRU for that root. ``cache_caps`` is required and selects that LRU.
    ``read_document`` returns a copy. ``load_document``
    returns the retained tree or the object just read from disk.
    ``replace_document`` persists the given object and keeps it in the LRU.
    """

    def __init__(self, storage_root: Path, *, cache_caps: DocumentCacheCaps) -> None:
        self._root = storage_root
        self._document_lru = document_lru_for_root(storage_root, cache_caps)

    def iter_document_paths(self) -> Iterator[str]:
        root = self._root
        if not root.is_dir():
            return
        for file_path in root.rglob("*.json"):
            if file_path.name.startswith("."):
                continue
            relative = file_path.relative_to(root).as_posix()
            if relative.endswith(".json"):
                yield relative[: -len(".json")]

    def has_document(self, breakpoint_path: str) -> bool:
        return self._document_file(breakpoint_path).is_file()

    def read_document(self, breakpoint_path: str) -> JSONValue:
        return deep_copy_value(self.load_document(breakpoint_path))

    def write_document(self, breakpoint_path: str, value: JSONValue) -> None:
        self.replace_document(breakpoint_path, deep_copy_value(value))

    def replace_document(self, breakpoint_path: str, value: JSONValue) -> None:
        """Persist ``value`` and retain that same object in the LRU."""
        file_path = self._document_file(breakpoint_path)
        byte_size = self._atomic_write(file_path, value)
        self._document_lru.remember_document(
            breakpoint_path,
            value,
            byte_size=byte_size,
        )

    def remove_document(self, breakpoint_path: str) -> None:
        file_path = self._document_file(breakpoint_path)
        try:
            file_path.unlink()
        except FileNotFoundError:
            raise NotFoundError(f"Document not found: {breakpoint_path!r}") from None
        self._document_lru.drop_document(breakpoint_path)
        self._prune_empty_dirs(file_path.parent)

    def load_document(self, breakpoint_path: str) -> JSONValue:
        """Return the retained tree, or the object just read from disk.

        ``read_document`` returns a copy of this value.
        """
        cached, epoch = self._document_lru.get_document(breakpoint_path)
        if cached is not None:
            return cached
        file_path = self._document_file(breakpoint_path)
        try:
            with open(file_path, "rb") as handle:
                raw = handle.read()
        except FileNotFoundError:
            # Concurrent delete/prune can unlink between a peer's write and this
            # open (same race as ``_ensure_dir`` after a persistence clear).
            raise NotFoundError(f"Document not found: {breakpoint_path!r}") from None
        loaded = json.loads(raw)
        self._document_lru.fill_document(
            breakpoint_path,
            loaded,
            epoch=epoch,
            byte_size=len(raw),
        )
        return loaded

    @contextmanager
    def document_lock(self, breakpoint_path: str) -> Iterator[None]:
        """Serialize read-modify-write of one breakpoint document on this root."""
        with self._document_lru.document_lock(breakpoint_path):
            yield

    def child_names(self, prefix: str) -> list[str]:
        if prefix == "" and not self._root.is_dir():
            return []
        return self._list_filesystem_prefix(prefix)

    def _document_file(self, breakpoint_path: str) -> Path:
        return self._root / document_relpath(breakpoint_path)

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

    def _write_replaced(self, file_path: Path, value: JSONValue) -> int:
        """Atomically replace ``file_path`` and return its byte size."""
        self._ensure_dir(file_path.parent)
        payload = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
        temp_path = file_path.with_name(
            f".{file_path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        try:
            with open(temp_path, "wb") as handle:
                handle.write(payload)
            os.replace(temp_path, file_path)
        finally:
            temp_path.unlink(missing_ok=True)
        return len(payload)

    def _atomic_write(self, file_path: Path, value: JSONValue, *, attempts: int = 8) -> int:
        """Write ``value`` via temp + replace, retrying when a peer prunes the parent.

        After a persistence clear, concurrent fleet/scores puts share
        ``…/turns/N/analytics``. A pruner can remove that directory after
        ``_ensure_dir`` and before ``open`` / ``os.replace``, which raises
        ``FileNotFoundError`` with the destination path (e.g. ``fleet.json``).
        Returns the byte size of the written file.
        """
        validate_no_reserved_at_keys(value)
        for _ in range(attempts):
            try:
                return self._write_replaced(file_path, value)
            except FileNotFoundError:
                continue
        relative_path = file_path.relative_to(self._root).as_posix()
        raise NotFoundError(f"Document not found: {relative_path!r}")

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
