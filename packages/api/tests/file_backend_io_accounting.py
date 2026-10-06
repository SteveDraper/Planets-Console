"""Call-count instrumentation for FileStorageBackend worker I/O.

Wraps the existing file backend; this is not a second storage implementation.
Counts are protocol methods (get/put/list/delete) plus the open / json / iterdir
/ stat primitives the file document store uses. Assertions should lock those
counts or overlap ratios, not wall milliseconds.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from api.storage.base import JSONValue, StorageBackend

from tests.file_storage_helpers import open_file_storage_backend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"

GAME_ID = 628580
PERSPECTIVE = 1
TURN_NUMBER = 111
TURN_KEY = f"games/{GAME_ID}/{PERSPECTIVE}/turns/{TURN_NUMBER}"
ANALYTICS_PREFIX = f"{TURN_KEY}/analytics"
FLEET_KEY = f"{ANALYTICS_PREFIX}/fleet"
TURNS_PREFIX = f"games/{GAME_ID}/{PERSPECTIVE}/turns"

# Sibling analytic documents so ``list(analytics)`` stats a populated directory.
ANALYTIC_SIBLINGS: tuple[str, ...] = (
    "fleet",
    "scores",
    "homeworld-locator",
    "aux-0",
    "aux-1",
    "aux-2",
    "aux-3",
    "aux-4",
)


@dataclass
class FileIoCounts:
    get_calls: int = 0
    put_calls: int = 0
    list_calls: int = 0
    delete_calls: int = 0
    open_calls: int = 0
    open_read_calls: int = 0
    open_write_calls: int = 0
    json_load_calls: int = 0
    json_dump_calls: int = 0
    stat_calls: int = 0
    iterdir_calls: int = 0
    is_dir_calls: int = 0
    is_file_calls: int = 0
    get_keys: list[str] = field(default_factory=list)
    list_prefixes: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.get_calls = 0
        self.put_calls = 0
        self.list_calls = 0
        self.delete_calls = 0
        self.open_calls = 0
        self.open_read_calls = 0
        self.open_write_calls = 0
        self.json_load_calls = 0
        self.json_dump_calls = 0
        self.stat_calls = 0
        self.iterdir_calls = 0
        self.is_dir_calls = 0
        self.is_file_calls = 0
        self.get_keys.clear()
        self.list_prefixes.clear()

    def protocol_counts(self) -> dict[str, int]:
        return {
            "get": self.get_calls,
            "put": self.put_calls,
            "list": self.list_calls,
            "delete": self.delete_calls,
        }

    def syscall_counts(self) -> dict[str, int]:
        return {
            "open": self.open_calls,
            "open_read": self.open_read_calls,
            "open_write": self.open_write_calls,
            "json_load": self.json_load_calls,
            "json_dump": self.json_dump_calls,
            "stat": self.stat_calls,
            "iterdir": self.iterdir_calls,
            "is_dir": self.is_dir_calls,
            "is_file": self.is_file_calls,
        }


class CountingStorageBackend:
    """Delegating ``StorageBackend`` spy; all I/O still goes to ``inner``."""

    def __init__(self, inner: StorageBackend, counts: FileIoCounts) -> None:
        self._inner = inner
        self.counts = counts

    def get(self, key: str) -> JSONValue:
        self.counts.get_calls += 1
        self.counts.get_keys.append(key)
        return self._inner.get(key)

    def put(self, key: str, value: JSONValue) -> None:
        self.counts.put_calls += 1
        self._inner.put(key, value)

    def delete(self, key: str) -> None:
        self.counts.delete_calls += 1
        self._inner.delete(key)

    def list(self, prefix: str) -> list[str]:
        self.counts.list_calls += 1
        self.counts.list_prefixes.append(prefix)
        return self._inner.list(prefix)


def load_turn_sample_json() -> dict[str, Any]:
    with open(ASSETS_DIR / "turn_sample.json", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError("turn_sample.json must be a JSON object")
    return payload


def load_game_info_sample_json() -> dict[str, Any]:
    with open(ASSETS_DIR / "game_info_sample.json", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError("game_info_sample.json must be a JSON object")
    return payload


def seed_file_store_tree(
    backend: StorageBackend,
    *,
    turn_numbers: tuple[int, ...] = (110, 111, 112),
    analytic_siblings: tuple[str, ...] = ANALYTIC_SIBLINGS,
) -> None:
    """Write a tmp tree shaped like ``turns/N.json`` plus ``turns/N/analytics/*.json``."""
    backend.put(f"games/{GAME_ID}/info", load_game_info_sample_json())
    turn_payload = load_turn_sample_json()
    for stored_turn in turn_numbers:
        turn_doc = dict(turn_payload)
        settings = dict(turn_doc.get("settings") or {})
        settings["turn"] = stored_turn
        turn_doc["settings"] = settings
        game = dict(turn_doc.get("game") or {})
        game["turn"] = stored_turn
        turn_doc["game"] = game
        backend.put(f"games/{GAME_ID}/{PERSPECTIVE}/turns/{stored_turn}", turn_doc)
        analytics_root = f"games/{GAME_ID}/{PERSPECTIVE}/turns/{stored_turn}/analytics"
        for analytic_id in analytic_siblings:
            backend.put(f"{analytics_root}/{analytic_id}", {"analyticId": analytic_id})


@contextmanager
def count_file_backend_syscalls(counts: FileIoCounts) -> Iterator[FileIoCounts]:
    """Count open / json / iterdir / stat used by ``api.storage.file_documents``."""
    real_open = open
    real_json_loads = json.loads
    real_json_dumps = json.dumps
    real_iterdir = Path.iterdir
    real_is_dir = Path.is_dir
    real_is_file = Path.is_file
    real_stat = Path.stat

    def counting_open(path: Any, *args: Any, **kwargs: Any) -> Any:
        counts.open_calls += 1
        mode = args[0] if args else kwargs.get("mode", "r")
        if any(flag in str(mode) for flag in ("w", "a", "x")):
            counts.open_write_calls += 1
        else:
            counts.open_read_calls += 1
        return real_open(path, *args, **kwargs)

    def counting_json_loads(*args: Any, **kwargs: Any) -> Any:
        counts.json_load_calls += 1
        return real_json_loads(*args, **kwargs)

    def counting_json_dumps(*args: Any, **kwargs: Any) -> Any:
        counts.json_dump_calls += 1
        return real_json_dumps(*args, **kwargs)

    def counting_stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        counts.stat_calls += 1
        return real_stat(self, *args, **kwargs)

    def counting_iterdir(self: Path) -> Any:
        counts.iterdir_calls += 1
        return real_iterdir(self)

    def counting_is_dir(self: Path) -> bool:
        counts.is_dir_calls += 1
        return real_is_dir(self)

    def counting_is_file(self: Path) -> bool:
        counts.is_file_calls += 1
        return real_is_file(self)

    with (
        patch("api.storage.file_documents.open", counting_open),
        patch("api.storage.file_documents.json.loads", counting_json_loads),
        patch("api.storage.file_documents.json.dumps", counting_json_dumps),
        patch.object(Path, "iterdir", counting_iterdir),
        patch.object(Path, "is_dir", counting_is_dir),
        patch.object(Path, "is_file", counting_is_file),
        patch.object(Path, "stat", counting_stat),
    ):
        yield counts


def make_counting_file_backend(storage_root: Path) -> tuple[CountingStorageBackend, FileIoCounts]:
    counts = FileIoCounts()
    inner = open_file_storage_backend(storage_root)
    return CountingStorageBackend(inner, counts), counts
