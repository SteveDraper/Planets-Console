"""Storage sub-layer: StorageBackend protocol and implementations.

Nothing outside this subpackage may reference a concrete implementation.
Import the protocol and types from here or from base.
"""

import json
from pathlib import Path

from api.config import get_config
from api.storage.base import JSONValue, StorageBackend
from api.storage.file import FileStorageBackend
from api.storage.memory_asset import MemoryAssetBackend
from api.storage.migrations import StorageMigration

__all__ = [
    "JSONValue",
    "StorageBackend",
    "clear_backend_cache",
    "get_storage",
    "production_migrations",
]

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


def production_migrations() -> tuple[StorageMigration, ...]:
    """Return the steps a process or maintenance script binds when opening a data directory."""
    from api.analytics.fleet.storage_migration import fleet_storage_migration

    return (fleet_storage_migration(),)


def get_storage() -> StorageBackend:
    """Return the configured storage backend (cached per process)."""
    global _backend_cache
    if _backend_cache is not None:
        return _backend_cache
    cfg = get_config()
    migrations = production_migrations()
    if cfg.storage_backend == "ephemeral":
        asset_path = Path(cfg.storage_asset_path) if cfg.storage_asset_path else None
        initial = _load_asset(asset_path)
        _backend_cache = MemoryAssetBackend(initial=initial, migrations=migrations)
    elif cfg.storage_backend == "file":
        _backend_cache = FileStorageBackend(Path(cfg.storage_root), migrations=migrations)
    else:
        raise ValueError(f"Unknown storage_backend: {cfg.storage_backend!r}")
    return _backend_cache


def clear_backend_cache() -> None:
    """Clear the cached backend (for tests after config change)."""
    global _backend_cache
    _backend_cache = None
    from api.analytics.fleet.fleet_table_stream_registry import (
        reset_fleet_table_stream_registry_for_tests,
    )
    from api.analytics.fleet.fleet_table_stream_scheduler import (
        reset_fleet_table_stream_scheduler_for_tests,
    )
    from api.analytics.military_score_inference.inference_scheduler import (
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.military_score_inference.inference_table_stream_registry import (
        reset_inference_table_stream_registry_for_tests,
    )
    from api.services.stack import clear_process_service_stack

    clear_process_service_stack()
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()
    reset_fleet_table_stream_scheduler_for_tests()
    reset_fleet_table_stream_registry_for_tests()
