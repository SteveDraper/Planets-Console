"""Read-through LRU turn cache for the compute orchestration plane."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from api.compute.dag import PlannedComputeNode
from api.compute.lru_cache import LruCache
from api.compute.scope import WILDCARD, ComputeScope
from api.models.game import TurnInfo

_DEFAULT_MAXSIZE = 128

TurnCacheKey = tuple[int, int, int]  # (game_id, perspective, turn)
LoadTurnFn = Callable[[int], TurnInfo | None]


@dataclass
class OrchestratorTurnCache:
    """Process-wide read-through LRU for ``TurnInfo``, keyed by shell + turn.

    Callers supply a shell-scoped ``load_turn`` on miss; hits never invoke it.
    """

    maxsize: int = _DEFAULT_MAXSIZE
    _cache: LruCache[TurnCacheKey, TurnInfo] = field(init=False, repr=False)
    _underlying_load_calls: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._cache = LruCache(self.maxsize)

    @property
    def underlying_load_calls(self) -> int:
        """Number of calls that reached a wrapped ``load_turn`` (tests/diagnostics)."""
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
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        self._underlying_load_calls += 1
        turn = load_turn(turn_number)
        if turn is not None:
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

    def clear(self) -> None:
        """Drop all cached turns (tests / orchestrator shutdown)."""
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
