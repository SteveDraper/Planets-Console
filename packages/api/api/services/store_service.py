"""Store service: CRUD over the logical JSON store with path semantics and merge rules."""

from __future__ import annotations

from api.errors import ConflictError, NotFoundError, ValidationError
from api.storage.base import JSONValue, StorageBackend
from api.storage.path_utils import (
    deep_copy_value,
    list_children,
    validate_no_reserved_at_keys,
)


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
        validate_no_reserved_at_keys(value)
        path_norm = (path or "").strip().strip("/") or ""
        try:
            self._storage.get(path_norm)
            raise ConflictError(f"Path already exists: {path_norm!r}")
        except NotFoundError:
            pass
        self._storage.put(path_norm, value)

    def read(self, path: str) -> JSONValue:
        """Return the node at path. Raises NotFoundError if path does not exist."""
        path_norm = (path or "").strip().strip("/") or ""
        return self._storage.get(path_norm)

    def read_shallow(self, path: str) -> dict:
        """Return shallow metadata: path, node_type, children, count."""
        path_norm = (path or "").strip().strip("/") or ""
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
            "path": path_norm or "(root)",
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
        validate_no_reserved_at_keys(value)
        path_norm = (path or "").strip().strip("/") or ""
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
        path_norm = (path or "").strip().strip("/") or ""
        self._storage.delete(path_norm)
