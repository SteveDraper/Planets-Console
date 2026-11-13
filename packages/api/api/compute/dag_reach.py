"""Reachability over the compute DAG's dependency edges.

One walk serves every caller that asks which nodes live work still reaches:
the band derivation carries a band down it, and a settle keeps the nodes it
reaches. It reads node state only and never mutates it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from api.compute.scope import ComputeScope


class DagReachNode(Protocol):
    """The node state the walk reads."""

    @property
    def dependency_scopes(self) -> tuple[ComputeScope, ...]: ...

    @property
    def is_terminal(self) -> bool: ...


def needed_scopes(
    nodes: Mapping[ComputeScope, DagReachNode],
    alive: Iterable[ComputeScope],
) -> frozenset[ComputeScope]:
    """Return the non-terminal scopes in ``alive`` and every scope they still need.

    A scope is needed when a reached scope depends on it and its node is
    non-terminal. The walk carries on through parked nodes. A terminal node,
    or a scope with no node in ``nodes``, ends that path.
    """

    def is_live(scope: ComputeScope) -> bool:
        node = nodes.get(scope)
        return node is not None and not node.is_terminal

    reached: set[ComputeScope] = set()
    pending = [scope for scope in alive if is_live(scope)]
    while pending:
        scope = pending.pop()
        if scope in reached:
            continue
        reached.add(scope)
        pending.extend(
            dependency
            for dependency in nodes[scope].dependency_scopes
            if dependency not in reached and is_live(dependency)
        )
    return frozenset(reached)
