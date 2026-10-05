"""Process storage opener: production migrations and the configured backend.

This composition module sits above ``api.storage`` and ``api.analytics``. It
binds analytic migration steps and instantiates the configured backend.
``api.storage`` must not import this module.
"""

import json
from dataclasses import replace
from pathlib import Path

from api.analytics.fleet.fleet_table_stream_registry import (
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.fleet.storage_migration import fleet_storage_migration
from api.analytics.military_score_inference.inference_scheduler import (
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.config import get_config
from api.services.stack import clear_process_service_stack
from api.storage.base import StorageBackend
from api.storage.file import FileStorageBackend
from api.storage.memory_asset import MemoryAssetBackend
from api.storage.migrations import (
    DEFAULT_STORAGE_FORMAT,
    StorageFormat,
    StorageMigration,
    require_contiguous_migration_versions,
)

_backend_cache: StorageBackend | None = None


def production_migrations() -> tuple[StorageMigration, ...]:
    """Return the steps a process or maintenance script binds when opening a data directory."""
    return (fleet_storage_migration(),)


def production_storage_format() -> StorageFormat:
    """Return the format a process or maintenance script uses to open a data directory.

    Bound steps must be contiguous versions ``1..current``. A gap is a registry
    bug and raises ``RuntimeError``.
    """
    storage_format = replace(DEFAULT_STORAGE_FORMAT, migrations=production_migrations())
    require_contiguous_migration_versions(
        storage_format.migrations,
        storage_format.current_version,
    )
    return storage_format


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
    storage_format = production_storage_format()
    if cfg.storage_backend == "ephemeral":
        asset_path = Path(cfg.storage_asset_path) if cfg.storage_asset_path else None
        initial = _load_asset(asset_path)
        _backend_cache = MemoryAssetBackend(initial=initial, storage_format=storage_format)
    elif cfg.storage_backend == "file":
        _backend_cache = FileStorageBackend(Path(cfg.storage_root), storage_format=storage_format)
    else:
        raise ValueError(f"Unknown storage_backend: {cfg.storage_backend!r}")
    return _backend_cache


def clear_backend_cache() -> None:
    """Clear the cached backend, service stack, and analytic singletons.

    Tests call this after a config change. Stream and scheduler singletons are
    process-wide, so this reset drops them with the backend.
    """
    global _backend_cache
    _backend_cache = None
    clear_process_service_stack()
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()
    reset_fleet_table_stream_scheduler_for_tests()
    reset_fleet_table_stream_registry_for_tests()
