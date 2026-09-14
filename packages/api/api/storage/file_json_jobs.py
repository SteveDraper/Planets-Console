"""Time sequential file-backend get/list/json jobs on a caller-supplied tmp tree."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from api.storage.file import FileStorageBackend

FILE_JSON_JOB_COUNT = 400
_GAME_ID = 628580
_PERSPECTIVE = 1
_TURN_NUMBER = 111
_TURN_KEY = f"games/{_GAME_ID}/{_PERSPECTIVE}/turns/{_TURN_NUMBER}"
_ANALYTICS_PREFIX = f"{_TURN_KEY}/analytics"
_FLEET_KEY = f"{_ANALYTICS_PREFIX}/fleet"
_ANALYTIC_SIBLINGS = ("fleet", "scores", "homeworld-locator")


@dataclass(frozen=True)
class FileJsonJobTiming:
    """Wall and protocol counts for N get+list+get jobs after a small seed."""

    job_count: int
    wall_seconds: float
    protocol_counts: dict[str, int]


def time_file_json_jobs(
    storage_root: Path,
    *,
    job_count: int = FILE_JSON_JOB_COUNT,
) -> FileJsonJobTiming:
    """Seed a tmp file store, then time ``job_count`` get/list/get cycles.

    Each job is ``get(turn)``, ``list(analytics)``, ``get(fleet)`` -- the same
    mix as the worker-I/O convoy characterization. ``storage_root`` must be a
    tmp tree, not the OS console data directory.
    """
    storage_root.mkdir(parents=True, exist_ok=True)
    backend = FileStorageBackend(storage_root)
    put_calls = 0
    backend.put(f"games/{_GAME_ID}/info", {"name": "probe"})
    put_calls += 1
    backend.put(_TURN_KEY, {"turn": _TURN_NUMBER})
    put_calls += 1
    for analytic_id in _ANALYTIC_SIBLINGS:
        backend.put(f"{_ANALYTICS_PREFIX}/{analytic_id}", {"analyticId": analytic_id})
        put_calls += 1

    get_calls = 0
    list_calls = 0
    started = time.perf_counter()
    for _ in range(job_count):
        backend.get(_TURN_KEY)
        get_calls += 1
        backend.list(_ANALYTICS_PREFIX)
        list_calls += 1
        backend.get(_FLEET_KEY)
        get_calls += 1
    wall_seconds = time.perf_counter() - started
    return FileJsonJobTiming(
        job_count=job_count,
        wall_seconds=wall_seconds,
        protocol_counts={
            "get": get_calls,
            "list": list_calls,
            "put": put_calls,
        },
    )
