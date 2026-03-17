"""In-memory StorageBackend initialized from a JSON asset; supports full CRUD for testing.

Backed by a deep copy of the initial data so all operations (get/put/delete/list) are
implemented and can be unit tested. Not read-only.
"""

from __future__ import annotations

from api.errors import NotFoundError
from api.storage.base import JSONValue
from api.storage.path_utils import (
    deep_copy_value,
    ensure_ancestors,
    list_children,
    parse_index_segment,
    resolve_parent_and_segment,
    resolve_path,
)


class MemoryAssetBackend:
    """Storage backend that holds a logical JSON tree in memory.

    Initialized from an initial payload (e.g. loaded from a test JSON asset).
    All mutations modify the in-memory dict; no persistence.
    """

    def __init__(self, initial: dict[str, JSONValue] | None = None) -> None:
        """Initialize with a deep copy of initial. Root is always a dict."""
        self._root: dict[str, JSONValue] = (
            deep_copy_value(initial or {}) if initial is not None else {}
        )

    def get(self, key: str) -> JSONValue:
        """Return a deep copy of the value at path. Raises NotFoundError if path does not exist."""
        path = (key or "").strip().strip("/") or ""
        if path == "":
            return deep_copy_value(self._root)
        node = resolve_path(self._root, path)
        return deep_copy_value(node)

    def put(self, key: str, value: JSONValue) -> None:
        """Store value at path. Creates object ancestors as needed. Overwrites if path exists."""
        path = (key or "").strip().strip("/") or ""
        value_copy = deep_copy_value(value)
        if path == "":
            if not isinstance(value_copy, dict):
                raise ValueError("Root must be a JSON object")
            self._root.clear()
            self._root.update(value_copy)
            return
        parent, segment, is_array_index = ensure_ancestors(self._root, path)
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

    def delete(self, key: str) -> None:
        """Remove the node at path. Raises NotFoundError if path does not exist."""
        path = (key or "").strip().strip("/") or ""
        if path == "":
            self._root.clear()
            return
        parent, segment, is_array_index = resolve_parent_and_segment(self._root, path)
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

    def list(self, prefix: str) -> list[str]:
        """Return next-hop segment names under the prefix."""
        path = (prefix or "").strip().strip("/") or ""
        if path == "":
            return list_children(self._root)
        node = resolve_path(self._root, path)
        return list_children(node)
