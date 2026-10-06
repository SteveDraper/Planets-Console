"""Shared file-backend opener for tests.

Production openers pass ``DocumentCacheCaps`` from config. Tests that do not
care which caps they use share ``DEFAULT_DOCUMENT_CACHE_CAPS`` (the ``ApiConfig``
field defaults) so call sites do not repeat those sizes.
"""

from __future__ import annotations

from pathlib import Path

from api.config import ApiConfig
from api.storage.document_lru import DocumentCacheCaps
from api.storage.file import FileStorageBackend
from api.storage.migrations import StorageFormat
from api.storage_factory import document_cache_caps_from_config

DEFAULT_DOCUMENT_CACHE_CAPS = document_cache_caps_from_config(ApiConfig())


def open_file_storage_backend(
    storage_root: Path,
    *,
    storage_format: StorageFormat | None = None,
    cache_caps: DocumentCacheCaps = DEFAULT_DOCUMENT_CACHE_CAPS,
) -> FileStorageBackend:
    """Open a file backend with explicit cache caps.

    Omitting ``cache_caps`` uses ``DEFAULT_DOCUMENT_CACHE_CAPS``.
    """
    return FileStorageBackend(
        storage_root,
        cache_caps=cache_caps,
        storage_format=storage_format,
    )
