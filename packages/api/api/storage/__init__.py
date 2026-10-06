"""Storage sub-layer: StorageBackend protocol and implementations.

Nothing outside this subpackage may reference a concrete implementation,
except the process storage factory which opens the configured backend.
Import the protocol and types from here or from base.
"""

from api.storage.base import JSONValue, StorageBackend

__all__ = [
    "JSONValue",
    "StorageBackend",
]
