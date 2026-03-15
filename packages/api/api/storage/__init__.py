"""Storage sub-layer: StorageBackend protocol and implementations.

Nothing outside this subpackage may reference a concrete implementation.
Import the protocol and types from here or from base.
"""
import json
from pathlib import Path

from api.storage.base import JSONValue, StorageBackend
from api.storage.memory_asset import MemoryAssetBackend

__all__ = ["JSONValue", "StorageBackend", "get_storage"]


def _load_test_asset() -> dict:
    """Load the default test JSON asset for the in-memory backend."""
    assets_dir = Path(__file__).resolve().parent / "assets"
    path = assets_dir / "store_test.json"
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_storage() -> StorageBackend:
    """Return the configured storage backend (in-memory asset-backed for now)."""
    return MemoryAssetBackend(initial=_load_test_asset())
