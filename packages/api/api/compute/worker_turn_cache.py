"""Process-local TurnInfo LRU fills for compute-plane workers.

Fleet materialize/observation legs deserialize ``turnWire`` through the
process TurnInfo cache. Storage fills use the same key; a worker reuses one
``StorageBackend`` from ``get_storage`` rather than opening a new file
backend per job. SAT-session children never import this module.
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
from api.storage.base import StorageBackend

_worker_storage: StorageBackend | None = None


def init_worker_turn_cache() -> None:
    """Reset worker-local turn cache and storage handle (pool initializer)."""
    global _worker_storage
    replace_process_turn_info_cache(maxsize=worker_turn_info_cache_maxsize())
    _worker_storage = None


def worker_deserialize_calls() -> int:
    """Number of TurnInfo fills performed in this worker (tests/diagnostics)."""
    return get_process_turn_info_cache().underlying_load_calls


def reset_worker_deserialize_calls_for_tests() -> None:
    """Reset fill counter in the current worker (tests only)."""
    get_process_turn_info_cache().reset_fill_calls()


def worker_storage_backend() -> StorageBackend:
    """Return one process storage backend, reused for storage TurnInfo fills."""
    global _worker_storage
    if _worker_storage is None:
        from api.storage import get_storage

        _worker_storage = get_storage()
    return _worker_storage


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


def turn_from_storage(
    game_id: int,
    perspective: int,
    turn_number: int,
    *,
    storage: StorageBackend | None = None,
) -> TurnInfo:
    """Load TurnInfo from storage once per worker for the same turn key."""
    from api.services.storage_json import require_dict
    from api.services.turn_load_service import TurnLoadService

    backend = storage if storage is not None else worker_storage_backend()

    def load(_turn_number: int) -> TurnInfo | None:
        data = backend.get(TurnLoadService.turn_store_key(game_id, perspective, turn_number))
        return turn_info_from_json(
            require_dict(
                data,
                f"turn {turn_number} of game {game_id} perspective {perspective}",
            )
        )

    turn = get_process_turn_info_cache().get(
        game_id,
        perspective,
        turn_number,
        load_turn=load,
    )
    if turn is None:
        raise TypeError("stored turn document deserialized to no TurnInfo")
    return turn
