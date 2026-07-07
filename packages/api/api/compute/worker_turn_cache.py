"""Per-worker LRU for deserializing prefetched turn wires in compute plane steps."""

from __future__ import annotations

from typing import Any

from api.compute.lru_cache import LruCache
from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json

_DEFAULT_MAXSIZE = 32

_cache = LruCache[tuple[int, int, int], TurnInfo](_DEFAULT_MAXSIZE)
_deserialize_calls = 0


def init_worker_turn_cache() -> None:
    """Reset worker-local turn cache (pool initializer)."""
    global _deserialize_calls
    _cache.clear()
    _deserialize_calls = 0


def worker_deserialize_calls() -> int:
    """Number of JSON deserializations performed in this worker (tests/diagnostics)."""
    return _deserialize_calls


def reset_worker_deserialize_calls_for_tests() -> None:
    """Reset deserialize counter in the current worker (tests only)."""
    global _deserialize_calls
    _deserialize_calls = 0


def turn_from_materialization_job_wire(job_wire: dict[str, Any]) -> TurnInfo:
    """Deserialize ``turnWire`` once per worker for repeated legs at the same turn."""
    global _deserialize_calls
    key = (
        int(job_wire["gameId"]),
        int(job_wire["perspective"]),
        int(job_wire["materializeTurn"]),
    )
    cached = _cache.get(key)
    if cached is not None:
        return cached

    _deserialize_calls += 1
    turn = turn_info_from_json(job_wire["turnWire"])
    _cache.put(key, turn)
    return turn
