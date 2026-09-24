"""Process-local TurnInfo LRU fills for compute-plane workers.

Fleet observation and materialization legs hydrate a scoreboard slice locally
and do not write that slice into this cache. SAT-session children never import
this module.
"""

from __future__ import annotations

from api.compute.turn_cache import (
    get_process_turn_info_cache,
    replace_process_turn_info_cache,
    worker_turn_info_cache_maxsize,
)


def init_worker_turn_cache() -> None:
    """Reset worker-local turn cache (pool initializer)."""
    replace_process_turn_info_cache(maxsize=worker_turn_info_cache_maxsize())


def worker_deserialize_calls() -> int:
    """Number of TurnInfo fills performed in this worker (tests/diagnostics)."""
    return get_process_turn_info_cache().underlying_load_calls


def reset_worker_deserialize_calls_for_tests() -> None:
    """Reset fill counter in the current worker (tests only)."""
    get_process_turn_info_cache().reset_fill_calls()
