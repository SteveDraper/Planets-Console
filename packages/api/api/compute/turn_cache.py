"""Process-local read-through LRU for ``TurnInfo``.

One cache per process, keyed by ``(game_id, perspective, turn)``. Scores and
storage ``TurnInfo`` loads share it. Fleet observation and materialization
``turnWire`` is a scoreboard slice hydrated in the leg; that slice is not
stored under this key. Parent orchestrator splice uses this type and key;
worker heaps stay separate. This is not a ``StorageBackend`` document cache.

Module imports stay interpreter-safe (no DAG, FastAPI, or file storage) so
interpreter workers can initialize this cache.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from api.lru_cache import LruCache
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.compute.dag import PlannedComputeNode
    from api.compute.scope import ComputeScope

_DEFAULT_MAXSIZE = 128
_WORKER_MAXSIZE = 32

TurnCacheKey = tuple[int, int, int]  # (game_id, perspective, turn)
LoadTurnFn = Callable[[int], TurnInfo | None]


@dataclass
class TurnInfoCache:
    """Read-through LRU for ``TurnInfo``, keyed by shell + turn.

    Callers supply a fill ``load_turn`` on miss; hits never invoke it.
    Fill functions load a stored turn. The fleet scoreboard slice is not a fill.
    """

    maxsize: int = _DEFAULT_MAXSIZE
    _cache: LruCache[TurnCacheKey, TurnInfo] = field(init=False, repr=False)
    _lock: threading.Lock = field(init=False, repr=False)
    _underlying_load_calls: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._cache = LruCache(self.maxsize)
        self._lock = threading.Lock()

    @property
    def underlying_load_calls(self) -> int:
        """Number of calls that reached a wrapped fill function (tests/diagnostics)."""
        return self._underlying_load_calls

    def get(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        *,
        load_turn: LoadTurnFn,
    ) -> TurnInfo | None:
        """Read-through LRU lookup for one stored turn under a game/perspective shell."""
        key: TurnCacheKey = (game_id, perspective, turn_number)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            self._underlying_load_calls += 1
        turn = load_turn(turn_number)
        if turn is None:
            return None
        with self._lock:
            existing = self._cache.get(key)
            if existing is not None:
                return existing
            self._cache.put(key, turn)
        return turn

    def prefetch(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        *,
        load_turn: LoadTurnFn,
    ) -> TurnInfo | None:
        """Warm the cache for one turn (same semantics as :meth:`get`)."""
        return self.get(game_id, perspective, turn_number, load_turn=load_turn)

    def prefetch_planned_nodes(
        self,
        planned_nodes: Iterable[PlannedComputeNode],
        *,
        load_turn: LoadTurnFn,
        game_id: int,
        perspective: int,
    ) -> None:
        """Warm turns referenced by a planned compute DAG under one shell."""
        for planned in planned_nodes:
            self._prefetch_scope_turn(
                planned.scope,
                load_turn=load_turn,
                game_id=game_id,
                perspective=perspective,
            )
            for dependency_scope in planned.dependency_scopes:
                self._prefetch_scope_turn(
                    dependency_scope,
                    load_turn=load_turn,
                    game_id=game_id,
                    perspective=perspective,
                )

    def put(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        turn: TurnInfo,
    ) -> None:
        """Insert or replace a cached turn after that turn document is written."""
        with self._lock:
            self._cache.put((game_id, perspective, turn_number), turn)

    def drop(self, game_id: int, perspective: int, turn_number: int) -> None:
        """Forget a cached turn after that turn document is written without a TurnInfo."""
        with self._lock:
            self._cache.drop((game_id, perspective, turn_number))

    def reset_fill_calls(self) -> None:
        """Reset the fill counter without dropping entries (tests/diagnostics)."""
        with self._lock:
            self._underlying_load_calls = 0

    def clear(self) -> None:
        """Drop all cached turns (tests / orchestrator shutdown)."""
        with self._lock:
            self._cache = LruCache(self.maxsize)
            self._underlying_load_calls = 0

    def _prefetch_scope_turn(
        self,
        scope: ComputeScope,
        *,
        load_turn: LoadTurnFn,
        game_id: int,
        perspective: int,
    ) -> None:
        from api.compute.scope import WILDCARD

        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            return
        shell_game_id = scope.game_id if isinstance(scope.game_id, int) else game_id
        shell_perspective = scope.perspective if isinstance(scope.perspective, int) else perspective
        self.prefetch(
            shell_game_id,
            shell_perspective,
            scope.turn,
            load_turn=load_turn,
        )


_process_cache_lock = threading.Lock()
_process_cache: TurnInfoCache | None = None


def get_process_turn_info_cache() -> TurnInfoCache:
    """Return this process's TurnInfo LRU (parent splice and worker heaps)."""
    global _process_cache
    with _process_cache_lock:
        if _process_cache is None:
            _process_cache = TurnInfoCache()
        return _process_cache


def replace_process_turn_info_cache(*, maxsize: int = _DEFAULT_MAXSIZE) -> TurnInfoCache:
    """Install a fresh process cache (worker pool initializer)."""
    global _process_cache
    with _process_cache_lock:
        _process_cache = TurnInfoCache(maxsize=maxsize)
        return _process_cache


def clear_process_turn_info_cache() -> None:
    """Drop every cached turn in this process (tests / orchestrator shutdown)."""
    get_process_turn_info_cache().clear()


def worker_turn_info_cache_maxsize() -> int:
    """LRU bound used when initializing interpreter/process fleet workers."""
    return _WORKER_MAXSIZE
