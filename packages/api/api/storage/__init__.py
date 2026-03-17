"""Storage sub-layer: StorageBackend protocol and implementations.

Nothing outside this subpackage may reference a concrete implementation.
Import the protocol and types from here or from base.
"""

import json
from pathlib import Path

from api.config import get_config
from api.storage.base import JSONValue, StorageBackend
from api.storage.memory_asset import MemoryAssetBackend

__all__ = ["JSONValue", "StorageBackend", "get_storage", "clear_backend_cache"]

_backend_cache: StorageBackend | None = None


def _load_asset(path: Path | None) -> dict:
    """Load JSON from path; if path is None, return empty dict.

    If path is set but not a file, raise.
    """
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"Storage asset path is not a file: {path!s}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_storage() -> StorageBackend:
    """Return the configured storage backend (cached per process)."""
    global _backend_cache
    if _backend_cache is not None:
        return _backend_cache
    cfg = get_config()
    if cfg.storage_backend != "ephemeral":
        raise ValueError(f"Unknown storage_backend: {cfg.storage_backend!r}")
    asset_path = Path(cfg.storage_asset_path) if cfg.storage_asset_path else None
    initial = _load_asset(asset_path)
    _backend_cache = MemoryAssetBackend(initial=initial)
    return _backend_cache


def clear_backend_cache() -> None:
    """Clear the cached backend (for tests after config change)."""
    global _backend_cache
    _backend_cache = None
