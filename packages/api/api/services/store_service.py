"""Store service: CRUD over the logical JSON store with path semantics and merge rules.

The storage-meta namespace (the first segment of ``STORAGE_VERSION_KEY`` and
every path under it) is not part of this API. Create, read, update, delete,
and shallow listing of that namespace raise ``ValidationError`` whether or not
the path exists. A shallow listing of the store root omits that segment.
Backends and migrations still read and write the version stamp directly.
"""

from __future__ import annotations

from api.errors import ConflictError, NotFoundError, ValidationError
from api.storage.base import JSONValue, StorageBackend
from api.storage.boundaries import is_navigable_prefix, is_registered_path
from api.storage.migrations import STORAGE_VERSION_KEY
from api.storage.path_utils import (
    deep_copy_value,
    list_children,
    normalize_store_key,
    validate_no_reserved_at_keys,
)

_STORAGE_META_NAMESPACE = STORAGE_VERSION_KEY.split("/", 1)[0]


def _normalize_store_path(path: str) -> str:
    """Return the logical path, rejecting the storage-meta namespace."""
    path_norm = normalize_store_key(path)
    if path_norm == _STORAGE_META_NAMESPACE or path_norm.startswith(f"{_STORAGE_META_NAMESPACE}/"):
        raise ValidationError(f"Path is reserved for storage metadata: {path_norm!r}")
    return path_norm


def _children_visible_to_store(parent: str, children: list[str]) -> list[str]:
    """Drop the storage-meta segment from a root listing. Backend ``list`` is unchanged."""
    if parent != "":
        return children
    return [child for child in children if child != _STORAGE_META_NAMESPACE]


def _deep_merge_object(target: dict[str, JSONValue], source: dict[str, JSONValue]) -> None:
    """Merge source into target in place.

    Only for dicts; arrays and primitives in source overwrite.
    """
    for k, v in source.items():
        if k.startswith("@"):
            raise ValidationError(f"Reserved key in payload: {k!r}")
        if k in target and isinstance(target[k], dict) and isinstance(v, dict):
            _deep_merge_object(target[k], v)
        else:
            target[k] = deep_copy_value(v)


class StoreService:
    """Service for create/read/update/delete on the store with path semantics."""

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def create(self, path: str, value: JSONValue) -> None:
        """Create a node at path. Path must not exist. Ancestor objects are created as needed."""
        path_norm = _normalize_store_path(path)
        validate_no_reserved_at_keys(value)
        try:
            self._storage.get(path_norm)
            raise ConflictError(f"Path already exists: {path_norm!r}")
        except NotFoundError:
            pass
        self._storage.put(path_norm, value)

    def read(self, path: str) -> JSONValue:
        """Return the node at path. Raises NotFoundError if path does not exist."""
        path_norm = _normalize_store_path(path)
        return self._storage.get(path_norm)

    def read_shallow(self, path: str) -> dict:
        """Return shallow metadata: path, node_type, children, count."""
        path_norm = _normalize_store_path(path)
        if not is_navigable_prefix(path_norm):
            raise ValidationError(f"Unregistered store path prefix: {path_norm!r}")

        if path_norm == "" or not is_registered_path(path_norm):
            children = _children_visible_to_store(path_norm, self._storage.list(path_norm))
            return {
                "path": path_norm,
                "node_type": "object",
                "children": children,
                "count": len(children),
            }

        node = self._storage.get(path_norm)
        children = list_children(node)
        if isinstance(node, dict):
            node_type = "object"
            count = len(node)
        elif isinstance(node, list):
            node_type = "array"
            count = len(node)
        elif node is None:
            node_type = "null"
            count = 0
        elif isinstance(node, bool):
            node_type = "boolean"
            count = 0
        elif isinstance(node, int):
            node_type = "integer"
            count = 0
        elif isinstance(node, float):
            node_type = "number"
            count = 0
        else:
            node_type = "string"
            count = 0
        return {
            "path": path_norm,
            "node_type": node_type,
            "children": children,
            "count": count,
        }

    def update(
        self,
        path: str,
        value: JSONValue,
        *,
        merge_array: str | None = None,
    ) -> JSONValue:
        """Update node at path by merge (objects) or replace/append/prepend (arrays).
        merge_array: None = replace, 'append' = append, 'prepend' = prepend.
        Raises NotFoundError if path does not exist, ConflictError if type would change.
        """
        path_norm = _normalize_store_path(path)
        validate_no_reserved_at_keys(value)
        existing = self._storage.get(path_norm)

        if isinstance(existing, dict):
            if not isinstance(value, dict):
                raise ConflictError("Update would change node type from object to non-object")
            merged = deep_copy_value(existing)
            _deep_merge_object(merged, value)
            self._storage.put(path_norm, merged)
            return merged

        if isinstance(existing, list):
            if not isinstance(value, list) and merge_array is None:
                raise ConflictError("Update would change node type from array to non-array")
            if merge_array == "append":
                new_list = list(existing) if isinstance(existing, list) else []
                if isinstance(value, list):
                    new_list.extend(deep_copy_value(v) for v in value)
                else:
                    new_list.append(deep_copy_value(value))
                self._storage.put(path_norm, new_list)
                return new_list
            if merge_array == "prepend":
                new_list = list(existing) if isinstance(existing, list) else []
                if isinstance(value, list):
                    for v in reversed(value):
                        new_list.insert(0, deep_copy_value(v))
                else:
                    new_list.insert(0, deep_copy_value(value))
                self._storage.put(path_norm, new_list)
                return new_list
            # replace
            if not isinstance(value, list):
                raise ConflictError("Update would change node type from array to non-array")
            self._storage.put(path_norm, deep_copy_value(value))
            return self._storage.get(path_norm)

        # primitive or null: allow replace only with same kind; reject object/array
        if isinstance(value, (dict, list)):
            raise ConflictError(
                "Update would change node type from primitive/null to object or array."
            )
        self._storage.put(path_norm, deep_copy_value(value))
        return self._storage.get(path_norm)

    def delete(self, path: str) -> None:
        """Remove the node at path. Raises NotFoundError if path does not exist."""
        path_norm = _normalize_store_path(path)
        self._storage.delete(path_norm)
