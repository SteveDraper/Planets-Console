"""Time file-backend jobs on a caller-supplied tmp tree (tiny mix + large document)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from api.storage.base import JSONValue, StorageBackend
from api.storage.file import FileStorageBackend
from api.storage.path_utils import deep_copy_value

FILE_JSON_JOB_COUNT = 400
LARGE_DOCUMENT_TARGET_BYTES = 775_000
LARGE_DOCUMENT_TARGET_NODES = 38_000
LARGE_DOCUMENT_PLAYER_COUNT = 11
LARGE_DOCUMENT_WORKER_COUNT = 8
LARGE_DOCUMENT_ITERATIONS = 8
_GAME_ID = 628580
_PERSPECTIVE = 1
_TURN_NUMBER = 111
_TURN_KEY = f"games/{_GAME_ID}/{_PERSPECTIVE}/turns/{_TURN_NUMBER}"
_ANALYTICS_PREFIX = f"{_TURN_KEY}/analytics"
_FLEET_KEY = f"{_ANALYTICS_PREFIX}/fleet"
_ANALYTIC_SIBLINGS = ("fleet", "scores", "homeworld-locator")
_LARGE_FLEET_KEY = f"{_ANALYTICS_PREFIX}/fleet"
PROBE_GAME_ID = _GAME_ID
PROBE_PERSPECTIVE = _PERSPECTIVE
PROBE_TURN_NUMBER = _TURN_NUMBER
PROBE_TURN_KEY = _TURN_KEY
PROBE_FLEET_KEY = _FLEET_KEY


@dataclass(frozen=True)
class FileJsonJobTiming:
    """Wall and protocol counts for N get+list+get jobs after a small seed."""

    job_count: int
    wall_seconds: float
    protocol_counts: dict[str, int]


@dataclass(frozen=True)
class LargeDocumentJobTiming:
    """json.loads / deep_copy / get / put walls for a 683364-sized synthetic fleet document."""

    encoded_bytes: int
    node_count: int
    player_count: int
    iterations: int
    worker_count: int
    json_loads_single_seconds: float
    json_loads_eight_wall_seconds: float
    json_loads_throughput_ratio: float
    deep_copy_single_seconds: float
    deep_copy_eight_wall_seconds: float
    deep_copy_throughput_ratio: float
    get_single_seconds: float
    get_eight_wall_seconds: float
    get_throughput_ratio: float
    put_single_seconds: float
    put_eight_wall_seconds: float
    put_throughput_ratio: float

    def to_probe_json(self) -> dict[str, int | float]:
        """Wire object for ``--console-package-probe`` (uv vs frozen comparison)."""
        return {
            "encodedBytes": self.encoded_bytes,
            "nodeCount": self.node_count,
            "playerCount": self.player_count,
            "iterations": self.iterations,
            "workerCount": self.worker_count,
            "jsonLoadsSingleSeconds": self.json_loads_single_seconds,
            "jsonLoadsEightWallSeconds": self.json_loads_eight_wall_seconds,
            "jsonLoadsThroughputRatio": self.json_loads_throughput_ratio,
            "deepCopySingleSeconds": self.deep_copy_single_seconds,
            "deepCopyEightWallSeconds": self.deep_copy_eight_wall_seconds,
            "deepCopyThroughputRatio": self.deep_copy_throughput_ratio,
            "getSingleSeconds": self.get_single_seconds,
            "getEightWallSeconds": self.get_eight_wall_seconds,
            "getThroughputRatio": self.get_throughput_ratio,
            "putSingleSeconds": self.put_single_seconds,
            "putEightWallSeconds": self.put_eight_wall_seconds,
            "putThroughputRatio": self.put_throughput_ratio,
        }


def open_probe_file_backend(storage_root: Path) -> StorageBackend:
    """File backend on a caller tmp tree. Probe code must not import ``FileStorageBackend``."""
    storage_root.mkdir(parents=True, exist_ok=True)
    return FileStorageBackend(storage_root)


def json_node_count(value: JSONValue) -> int:
    """Count dicts, lists, and scalars in a JSON value (keys are not nodes)."""
    if isinstance(value, dict):
        return 1 + sum(json_node_count(item) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(json_node_count(item) for item in value)
    return 1


def synthetic_large_fleet_document(
    *,
    min_bytes: int = LARGE_DOCUMENT_TARGET_BYTES,
    min_nodes: int = LARGE_DOCUMENT_TARGET_NODES,
    player_count: int = LARGE_DOCUMENT_PLAYER_COUNT,
) -> dict[str, JSONValue]:
    """Deterministic fleet-shaped JSON ~775 KB / ~38k nodes. Not a game dump."""
    if player_count < 1:
        raise ValueError("player_count must be >= 1")
    ships_by_player: list[list[dict[str, JSONValue]]] = [[] for _ in range(player_count)]
    ship_id = 0
    document: dict[str, JSONValue] = {}
    encoded_bytes = 0
    nodes = 0
    while encoded_bytes < min_bytes or nodes < min_nodes:
        if ship_id < player_count:
            for player_index in range(player_count):
                ship_id += 1
                ships_by_player[player_index].append(_synthetic_ship(ship_id))
        else:
            ship_id += 1
            ships_by_player[0].append(_synthetic_ship(ship_id))
        if ship_id % 50 != 0 and encoded_bytes > 0:
            continue
        document = _fleet_document(ships_by_player)
        encoded_bytes = len(json.dumps(document, separators=(",", ":")).encode("utf-8"))
        nodes = json_node_count(document)
    return document


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


def time_large_document_jobs(
    storage_root: Path,
    *,
    document: dict[str, JSONValue] | None = None,
    iterations: int = LARGE_DOCUMENT_ITERATIONS,
    worker_count: int = LARGE_DOCUMENT_WORKER_COUNT,
) -> LargeDocumentJobTiming:
    """Time json.loads, deep_copy, get, and put of a 683364-sized fleet document.

    ``storage_root`` must be a tmp tree. Default document is
    ``synthetic_large_fleet_document()``. Each timed op runs ``iterations``
    times on one thread and again on ``worker_count`` threads (same iteration
    count per thread). Throughput ratio is ``(workers * single_wall) / eight_wall``.
    """
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if worker_count < 1:
        raise ValueError("worker_count must be >= 1")
    payload = document if document is not None else synthetic_large_fleet_document()
    encoded = json.dumps(payload, separators=(",", ":"))
    encoded_bytes = len(encoded.encode("utf-8"))
    parsed = json.loads(encoded)

    storage_root.mkdir(parents=True, exist_ok=True)
    backend = FileStorageBackend(storage_root)
    backend.put(f"games/{_GAME_ID}/info", {"name": "probe"})
    backend.put(_TURN_KEY, {"turn": _TURN_NUMBER})
    backend.put(_LARGE_FLEET_KEY, payload)
    backend.get(_LARGE_FLEET_KEY)

    loads_single = _repeat_wall(iterations, lambda: json.loads(encoded))
    loads_eight = _parallel_wall(
        worker_count, lambda: _repeat_unreturned(iterations, lambda: json.loads(encoded))
    )
    copy_single = _repeat_wall(iterations, lambda: deep_copy_value(parsed))
    copy_eight = _parallel_wall(
        worker_count, lambda: _repeat_unreturned(iterations, lambda: deep_copy_value(parsed))
    )
    get_single = _repeat_wall(iterations, lambda: backend.get(_LARGE_FLEET_KEY))
    get_eight = _parallel_wall(
        worker_count,
        lambda: _repeat_unreturned(iterations, lambda: backend.get(_LARGE_FLEET_KEY)),
    )
    put_single = _repeat_wall(iterations, lambda: backend.put(_LARGE_FLEET_KEY, payload))
    put_eight = _parallel_wall(
        worker_count,
        lambda: _repeat_unreturned(iterations, lambda: backend.put(_LARGE_FLEET_KEY, payload)),
    )
    return LargeDocumentJobTiming(
        encoded_bytes=encoded_bytes,
        node_count=json_node_count(payload),
        player_count=_ledger_player_count(payload),
        iterations=iterations,
        worker_count=worker_count,
        json_loads_single_seconds=loads_single,
        json_loads_eight_wall_seconds=loads_eight,
        json_loads_throughput_ratio=_throughput_ratio(loads_single, loads_eight, worker_count),
        deep_copy_single_seconds=copy_single,
        deep_copy_eight_wall_seconds=copy_eight,
        deep_copy_throughput_ratio=_throughput_ratio(copy_single, copy_eight, worker_count),
        get_single_seconds=get_single,
        get_eight_wall_seconds=get_eight,
        get_throughput_ratio=_throughput_ratio(get_single, get_eight, worker_count),
        put_single_seconds=put_single,
        put_eight_wall_seconds=put_eight,
        put_throughput_ratio=_throughput_ratio(put_single, put_eight, worker_count),
    )


def _synthetic_ship(ship_id: int) -> dict[str, JSONValue]:
    """One codec-valid fleet ship record (persistable prior ledger row)."""
    return {
        "recordId": f"probe-{ship_id:05d}",
        "disposition": "active",
        "qualifiers": {},
        "fields": {
            "shipId": {"kind": "known", "value": ship_id},
            "hull": {"kind": "known", "value": (ship_id % 50) + 1},
            "engine": {"kind": "unknown"},
            "beams": {"kind": "unknown"},
            "launchers": {"kind": "unknown"},
            "builtTurn": {"kind": "known", "value": 1},
            "location": {"kind": "unknown"},
        },
        "buildOptionSets": [],
        "events": [
            {
                "eventId": f"probe-ev-{ship_id:05d}",
                "kind": "scoreboard_delta",
                "turn": 1,
                "source": "probe",
                "payload": {"name": f"probe-ship-{ship_id:05d}"},
            }
        ],
    }


def _fleet_document(
    ships_by_player: list[list[dict[str, JSONValue]]],
) -> dict[str, JSONValue]:
    ledgers: dict[str, JSONValue] = {}
    for player_index, ships in enumerate(ships_by_player, start=1):
        ledgers[str(player_index)] = {
            "ledger": {
                "playerId": player_index,
                "playerName": f"probe-{player_index}",
                "records": ships,
            },
            "provenance": {"turnEvidenceAtN": False, "priorLedgerAtNMinus1": True},
            "materializationVersion": 1,
        }
    return {
        "analyticId": "fleet",
        "gameId": _GAME_ID,
        "perspective": _PERSPECTIVE,
        "turn": _TURN_NUMBER,
        "ledgers": ledgers,
    }


def _ledger_player_count(document: dict[str, JSONValue]) -> int:
    ledgers = document.get("ledgers")
    if isinstance(ledgers, dict):
        return len(ledgers)
    return 0


def _repeat_wall(iterations: int, operation: Callable[[], object]) -> float:
    started = time.perf_counter()
    for _ in range(iterations):
        operation()
    return time.perf_counter() - started


def _repeat_unreturned(iterations: int, operation: Callable[[], object]) -> None:
    for _ in range(iterations):
        operation()


def _parallel_wall(worker_count: int, worker: Callable[[], None]) -> float:
    barrier = threading.Barrier(worker_count + 1)
    errors: list[BaseException] = []

    def run() -> None:
        barrier.wait()
        try:
            worker()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(worker_count)]
    for thread in threads:
        thread.start()
    started = time.perf_counter()
    barrier.wait()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]
    return time.perf_counter() - started


def _throughput_ratio(single_wall: float, parallel_wall: float, worker_count: int) -> float:
    if parallel_wall <= 0.0:
        return float("inf")
    return (worker_count * single_wall) / parallel_wall
