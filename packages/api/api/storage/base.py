"""StorageBackend protocol and JSON value type for the store.

Path format: slash-separated segments, no leading slash. A segment may be
@N (e.g. @0, @-1) for array index. Object keys whose first character is @
are reserved and must not be stored.
"""
from typing import Protocol

# Recursive JSON type for store values (design §4)
JSONValue = (
    dict[str, "JSONValue"]
    | list["JSONValue"]
    | str
    | int
    | float
    | bool
    | None
)


class StorageBackend(Protocol):
    """Abstract interface for store access. All storage goes through this protocol."""

    def get(self, key: str) -> JSONValue:
        """Return the value at the path. Raises NotFoundError if path does not exist.
        Returns None only for a present JSON null node."""
        ...

    def put(self, key: str, value: JSONValue) -> None:
        """Store a value at the path. May create ancestors. Overwrites if path exists."""
        ...

    def delete(self, key: str) -> None:
        """Remove the node at the path. Raises NotFoundError if path does not exist."""
        ...

    def list(self, prefix: str) -> list[str]:
        """Return next-hop path segment names under the prefix (object keys or @0..@(n-1) for arrays)."""
        ...
