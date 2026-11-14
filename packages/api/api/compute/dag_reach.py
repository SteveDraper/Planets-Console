"""Reachability over the compute DAG's dependency edges.

One walk, :func:`dependency_closure`, serves every caller that asks which
nodes some work still reaches. The band derivation carries a band down it
from the nodes that hold that band. :func:`needed_scopes` starts it from live
work that is not running, so a settle keeps what that work needs. Both read
node state only and never mutate it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from api.compute.orchestrator_state import NodeState
    from api.compute.scope import ComputeScope


class DagReachNode(Protocol):
    """The node state the walk reads."""

    @property
    def dependency_scopes(self) -> tuple[ComputeScope, ...]: ...

    @property
    def is_terminal(self) -> bool: ...


class NeededNode(DagReachNode, Protocol):
    """The node state :func:`needed_scopes` reads."""

    @property
    def state(self) -> NodeState: ...


def dependency_closure(
    nodes: Mapping[ComputeScope, DagReachNode],
    roots: Iterable[ComputeScope],
) -> frozenset[ComputeScope]:
    """Return the non-terminal scopes in ``roots`` and every scope they transitively depend on.

    A dependency is reached when a reached scope depends on it and its node
    is non-terminal. The walk carries on through parked and running nodes. A
    terminal node, or a scope with no node in ``nodes``, ends that path.
    """

    def is_live(scope: ComputeScope) -> bool:
        node = nodes.get(scope)
        return node is not None and not node.is_terminal

    reached: set[ComputeScope] = set()
    pending = [scope for scope in roots if is_live(scope)]
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


def needed_scopes(
    nodes: Mapping[ComputeScope, NeededNode],
    alive: Iterable[ComputeScope],
) -> frozenset[ComputeScope]:
    """Return the scopes that the live work in ``alive`` still needs.

    The walk starts only from scopes in ``alive`` whose node is not running.
    A running node's job wire took its dependency outputs when it was
    dispatched, so it keeps no dependency alive on its own account. It is
    still needed when other needed work depends on it, and the walk then
    carries on through it, because it may run again.
    """
    return dependency_closure(
        nodes,
        (scope for scope in alive if scope in nodes and nodes[scope].state != "running"),
    )
