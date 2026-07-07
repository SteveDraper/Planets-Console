"""Read-through LRU turn cache for the compute orchestration plane."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from api.compute.dag import PlannedComputeNode
from api.compute.lru_cache import LruCache
from api.compute.scope import WILDCARD, ComputeScope
from api.models.game import TurnInfo

_DEFAULT_MAXSIZE = 128


@dataclass
class OrchestratorTurnCache:
    """Avoid repeated storage reads for ``TurnInfo`` on the main interpreter."""

    load_turn: Callable[[int], TurnInfo | None]
    maxsize: int = _DEFAULT_MAXSIZE
    _cache: LruCache[int, TurnInfo] = field(init=False, repr=False)
    _underlying_load_calls: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._cache = LruCache(self.maxsize)

    @property
    def underlying_load_calls(self) -> int:
        """Number of calls that reached the wrapped ``load_turn`` (tests/diagnostics)."""
        return self._underlying_load_calls

    def get(self, turn_number: int) -> TurnInfo | None:
        """Read-through LRU lookup for one stored turn number."""
        cached = self._cache.get(turn_number)
        if cached is not None:
            return cached

        self._underlying_load_calls += 1
        turn = self.load_turn(turn_number)
        if turn is not None:
            self._cache.put(turn_number, turn)
        return turn

    def prefetch(self, turn_number: int) -> TurnInfo | None:
        """Warm the cache for one turn (same semantics as :meth:`get`)."""
        return self.get(turn_number)

    def prefetch_planned_nodes(self, planned_nodes: Iterable[PlannedComputeNode]) -> None:
        """Warm turns referenced by a planned compute DAG."""
        for planned in planned_nodes:
            self._prefetch_scope_turn(planned.scope)
            for dependency_scope in planned.dependency_scopes:
                self._prefetch_scope_turn(dependency_scope)

    def _prefetch_scope_turn(self, scope: ComputeScope) -> None:
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            return
        self.prefetch(scope.turn)
