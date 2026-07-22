"""Durable StorageBackend: JSON documents at registry breakpoints on disk."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from api.errors import NotFoundError, ValidationError
from api.storage.base import JSONValue
from api.storage.boundaries import (
    document_relpath,
    is_navigable_prefix,
    is_prefix_of_longer_breakpoint,
    resolve_breakpoint,
)
from api.storage.path_utils import (
    deep_copy_value,
    ensure_ancestors,
    list_children,
    parse_index_segment,
    resolve_parent_and_segment,
    resolve_path,
    validate_no_reserved_at_keys,
)


class FileStorageBackend:
    """Persist the logical JSON store as breakpoint JSON files under ``storage_root``."""

    def __init__(self, storage_root: Path) -> None:
        self._root = storage_root

    def _normalize(self, key: str) -> str:
        return (key or "").strip().strip("/") or ""

    def _document_file(self, breakpoint_path: str) -> Path:
        return self._root / document_relpath(breakpoint_path)

    def _load_document(self, breakpoint_path: str) -> JSONValue:
        file_path = self._document_file(breakpoint_path)
        if not file_path.is_file():
            raise NotFoundError(f"Document not found: {breakpoint_path!r}")
        with open(file_path, encoding="utf-8") as handle:
            return json.load(handle)

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

    def _atomic_write(self, file_path: Path, value: JSONValue) -> None:
        validate_no_reserved_at_keys(value)
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
            if temp_path.exists():
                temp_path.unlink()

    def _prune_empty_dirs(self, start: Path) -> None:
        current = start
        while current != self._root and current.is_dir():
            try:
                next(current.iterdir())
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
        if not file_path.is_file():
            raise NotFoundError(f"Document not found: {breakpoint_path!r}")
        file_path.unlink()
        self._prune_empty_dirs(file_path.parent)

    def _list_filesystem_prefix(self, prefix: str) -> list[str]:
        dir_path = self._root if prefix == "" else self._root / prefix
        if not dir_path.is_dir():
            raise NotFoundError(f"Path does not exist: {prefix!r}")
        names: list[str] = []
        for entry in dir_path.iterdir():
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                names.append(entry.name)
            elif entry.is_file() and entry.suffix == ".json":
                names.append(entry.stem)
        return sorted(names)

    def get(self, key: str) -> JSONValue:
        path = self._normalize(key)
        if path == "":
            raise ValidationError("Cannot get root path")
        breakpoint_path, suffix = resolve_breakpoint(path)
        document = self._load_document(breakpoint_path)
        if suffix is None:
            return deep_copy_value(document)
        return deep_copy_value(resolve_path(document, suffix))

    def put(self, key: str, value: JSONValue) -> None:
        path = self._normalize(key)
        if path == "":
            raise ValidationError("Cannot put root path")
        breakpoint_path, suffix = resolve_breakpoint(path)
        value_copy = deep_copy_value(value)
        file_path = self._document_file(breakpoint_path)

        if suffix is None:
            self._atomic_write(file_path, value_copy)
            return

        if file_path.is_file():
            document = self._load_document(breakpoint_path)
        else:
            document = {}

        if not isinstance(document, dict):
            raise ValidationError(
                f"Cannot create nested path under non-object document: {breakpoint_path!r}"
            )

        parent, segment, is_array_index = ensure_ancestors(document, suffix)
        if is_array_index:
            idx = parse_index_segment(segment)
            if idx == len(parent):
                parent.append(value_copy)
            elif 0 <= idx < len(parent):
                parent[idx] = value_copy
            else:
                n = len(parent)
                if idx < 0:
                    idx += n
                if idx == n:
                    parent.append(value_copy)
                elif 0 <= idx < n:
                    parent[idx] = value_copy
                else:
                    raise NotFoundError(f"Array index out of range: {segment}")
        else:
            assert isinstance(parent, dict)
            parent[segment] = value_copy

        self._atomic_write(file_path, document)

    def delete(self, key: str) -> None:
        path = self._normalize(key)
        if path == "":
            raise ValidationError("Cannot delete root path")
        breakpoint_path, suffix = resolve_breakpoint(path)
        if suffix is None:
            self._delete_document(breakpoint_path)
            return

        document = self._load_document(breakpoint_path)
        parent, segment, is_array_index = resolve_parent_and_segment(document, suffix)
        if is_array_index:
            idx = parse_index_segment(segment)
            arr = parent
            if idx < 0:
                idx += len(arr)
            if idx < 0 or idx >= len(arr):
                raise NotFoundError(f"Array index out of range: {segment}")
            arr.pop(idx)
        else:
            assert isinstance(parent, dict)
            if segment not in parent:
                raise NotFoundError(f"Path does not exist: {segment!r}")
            del parent[segment]

        self._atomic_write(self._document_file(breakpoint_path), document)

    def list(self, prefix: str) -> list[str]:
        path = self._normalize(prefix)
        if not is_navigable_prefix(path):
            raise ValidationError(f"Unregistered store path prefix: {path!r}")

        if path == "":
            if not self._root.is_dir():
                return []
            return self._list_filesystem_prefix("")

        try:
            breakpoint_path, suffix = resolve_breakpoint(path)
        except ValidationError:
            return self._list_filesystem_prefix(path)

        # Intermediate prefixes between breakpoints (e.g. …/turns/N/analytics)
        # must list sibling analytic documents on disk, not a missing key inside
        # the shorter turn RST document.
        if suffix is not None and is_prefix_of_longer_breakpoint(path):
            return self._list_filesystem_prefix(path)

        file_path = self._document_file(breakpoint_path)
        if not file_path.is_file():
            raise NotFoundError(f"Path does not exist: {path!r}")

        document = self._load_document(breakpoint_path)
        if suffix is None:
            return list_children(document)
        node = resolve_path(document, suffix)
        return list_children(node)
