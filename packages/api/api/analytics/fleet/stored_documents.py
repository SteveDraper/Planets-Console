"""Read, delete, and list JSON documents under fleet storage keys."""

from __future__ import annotations

from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend


def list_segments(storage: StorageBackend, prefix: str) -> list[str]:
    """Child segments under ``prefix``; empty when the prefix is absent or invalid."""
    try:
        return storage.list(prefix)
    except NotFoundError, ValidationError:
        return []


def read_json_object(storage: StorageBackend, key: str) -> dict[str, object] | None:
    """The stored JSON object at ``key``, or ``None`` when nothing is stored."""
    try:
        data = storage.get(key)
    except NotFoundError:
        return None
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValidationError(f"stored fleet document at {key} must be a JSON object")
    return data


def delete_if_present(storage: StorageBackend, key: str) -> bool:
    """Delete ``key``. Return whether a document was present."""
    try:
        storage.delete(key)
    except NotFoundError:
        return False
    return True
