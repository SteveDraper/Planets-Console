"""Process-local TurnInfo LRU fills for compute-plane workers.

Fleet materialize/observation legs deserialize ``turnWire`` through the
process TurnInfo cache. SAT-session children never import this module.
"""

from __future__ import annotations

from typing import Any

from api.compute.turn_cache import (
    get_process_turn_info_cache,
    replace_process_turn_info_cache,
    worker_turn_info_cache_maxsize,
)
from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json


def init_worker_turn_cache() -> None:
    """Reset worker-local turn cache (pool initializer)."""
    replace_process_turn_info_cache(maxsize=worker_turn_info_cache_maxsize())


def worker_deserialize_calls() -> int:
    """Number of TurnInfo fills performed in this worker (tests/diagnostics)."""
    return get_process_turn_info_cache().underlying_load_calls


def reset_worker_deserialize_calls_for_tests() -> None:
    """Reset fill counter in the current worker (tests only)."""
    get_process_turn_info_cache().reset_fill_calls()


def turn_from_materialization_job_wire(job_wire: dict[str, Any]) -> TurnInfo:
    """Deserialize ``turnWire`` once per worker for repeated legs at the same turn."""
    game_id = int(job_wire["gameId"])
    perspective = int(job_wire["perspective"])
    turn_number = int(job_wire["materializeTurn"])
    turn_wire = job_wire["turnWire"]

    def load(_turn_number: int) -> TurnInfo | None:
        return turn_info_from_json(turn_wire)

    turn = get_process_turn_info_cache().get(
        game_id,
        perspective,
        turn_number,
        load_turn=load,
    )
    if turn is None:
        raise TypeError("turnWire deserialized to no TurnInfo")
    return turn
