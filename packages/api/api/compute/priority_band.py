"""Compute priority bands, shell stream watches, and the pure band derivation.

A band ranks orchestrator work for dispatch. A request asks for a standing
band (``interactive_ensure`` or ``background``). ``stream_attached`` is never
requested: a node derives it when it, or a non-terminal node that transitively
depends on it, is watched by a live shell stream.

A registration names the :class:`ShellStreamWatch` whose keys can make its
nodes watched. A watch's keys apply only to nodes registered with that watch,
so ``compute/`` never checks analytic ids to decide liveness.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from api.compute.registry import AnalyticComputeRegistration
    from api.compute.scope import ComputeScope

ComputePriorityBand = Literal["stream_attached", "interactive_ensure", "background"]
"""The band a node is dispatched and picked at."""

ComputeRequestBand = Literal["interactive_ensure", "background"]
"""The standing band a request may ask for."""

PRIORITY_BAND_RANK: Mapping[ComputePriorityBand, int] = MappingProxyType(
    {
        "stream_attached": 0,
        "interactive_ensure": 1,
        "background": 2,
    }
)
"""Dispatch rank per band; a lower rank goes first."""

_BANDS_BY_PRECEDENCE: tuple[ComputePriorityBand, ...] = tuple(
    sorted(PRIORITY_BAND_RANK, key=PRIORITY_BAND_RANK.__getitem__)
)


def highest_band[BandT: ComputePriorityBand](first: BandT, *rest: BandT) -> BandT:
    """Return the band that goes first among ``first`` and ``rest``."""
    return min((first, *rest), key=PRIORITY_BAND_RANK.__getitem__)


@dataclass(frozen=True)
class WatchedShellKey:
    """One live shell a stream watch reports: a player's view of a game turn."""

    game_id: int
    perspective: int
    turn: int
    player_id: int


class ShellStreamWatch(ABC):
    """Registration hook that reports which shells live streams are watching.

    Instances are compared by identity: the derivation looks up each node's
    keys snapshot by its registration's watch.
    """

    @abstractmethod
    def watched_keys(self) -> frozenset[WatchedShellKey]:
        """Return the shells watched now.

        Called under the orchestrator lock, so it must read lock-free
        snapshots only and never call back into the orchestrator.
        """


class _Unwatched(ShellStreamWatch):
    def watched_keys(self) -> frozenset[WatchedShellKey]:
        return frozenset()


UNWATCHED: ShellStreamWatch = _Unwatched()
"""The default watch: no stream ever watches the registration's nodes."""


class BandDerivationNode(Protocol):
    """The node state the band derivation reads."""

    @property
    def dependency_scopes(self) -> tuple[ComputeScope, ...]: ...

    @property
    def is_terminal(self) -> bool: ...

    @property
    def standing_band(self) -> ComputeRequestBand: ...


def _watched_shell_key(scope: ComputeScope) -> WatchedShellKey | None:
    """Return the shell key ``scope`` names, or None when an axis is not concrete."""
    perspective, turn, player_id = scope.perspective, scope.turn, scope.player_id
    if isinstance(perspective, int) and isinstance(turn, int) and isinstance(player_id, int):
        return WatchedShellKey(
            game_id=scope.game_id, perspective=perspective, turn=turn, player_id=player_id
        )
    return None


def _own_band(
    scope: ComputeScope,
    node: BandDerivationNode,
    watched: Mapping[ShellStreamWatch, frozenset[WatchedShellKey]],
    registry: Mapping[str, AnalyticComputeRegistration],
) -> ComputePriorityBand:
    key = _watched_shell_key(scope)
    if key is not None and key in watched[registry[scope.analytic_id].shell_stream_watch]:
        return "stream_attached"
    return node.standing_band


def derive_priority_bands(
    nodes: Mapping[ComputeScope, BandDerivationNode],
    watched: Mapping[ShellStreamWatch, frozenset[WatchedShellKey]],
    registry: Mapping[str, AnalyticComputeRegistration],
) -> Mapping[ComputeScope, ComputePriorityBand]:
    """Return the band of every non-terminal node.

    A node's own band is ``stream_attached`` when its shell key is in the
    ``watched`` snapshot of its registration's watch, and its standing band
    otherwise. Its derived band is the highest own band over the node and every
    non-terminal node that transitively depends on it; parked nodes count.
    Terminal nodes neither appear in the result nor carry a band through.

    ``watched`` holds one keys snapshot for every watch in ``registry``.
    """
    live_nodes = {scope: node for scope, node in nodes.items() if not node.is_terminal}
    own_bands = {
        scope: _own_band(scope, node, watched, registry) for scope, node in live_nodes.items()
    }
    bands: dict[ComputeScope, ComputePriorityBand] = {}
    for band in _BANDS_BY_PRECEDENCE:
        pending = [scope for scope, own in own_bands.items() if own == band]
        while pending:
            scope = pending.pop()
            if scope in bands:
                continue
            bands[scope] = band
            pending.extend(
                dependency
                for dependency in live_nodes[scope].dependency_scopes
                if dependency in live_nodes and dependency not in bands
            )
    return MappingProxyType(bands)
