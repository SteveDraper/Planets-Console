"""Unit table for the dependency closure and for what live work still needs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest
from api.compute.dag_reach import dependency_closure, needed_scopes
from api.compute.orchestrator_state import TERMINAL_NODE_STATES, NodeState
from api.compute.scope import ComputeScope


@dataclass
class _Node:
    dependency_scopes: tuple[ComputeScope, ...] = ()
    state: NodeState = "ready"

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_NODE_STATES


def _scope(name: str) -> ComputeScope:
    return ComputeScope(analytic_id=name, game_id=1, perspective=1, turn=40, player_id=7)


A, B, C, D, E = (_scope(name) for name in "abcde")


@dataclass(frozen=True)
class _Case:
    name: str
    nodes: Mapping[ComputeScope, _Node]
    scopes: tuple[ComputeScope, ...]
    expected: frozenset[ComputeScope]


# No node is running, so the closure from ``scopes`` is also what they need.
_SHARED_CASES = (
    _Case(
        name="no scope reaches nothing",
        nodes={A: _Node((B,)), B: _Node()},
        scopes=(),
        expected=frozenset(),
    ),
    _Case(
        name="a chain is reached through every hop",
        nodes={A: _Node((B,)), B: _Node((C,)), C: _Node()},
        scopes=(A,),
        expected=frozenset({A, B, C}),
    ),
    _Case(
        name="a chain is reached only below the starting scope",
        nodes={A: _Node((B,)), B: _Node((C,)), C: _Node()},
        scopes=(B,),
        expected=frozenset({B, C}),
    ),
    _Case(
        name="a diamond reaches its shared dependency once",
        nodes={A: _Node((B, C)), B: _Node((D,)), C: _Node((D,)), D: _Node()},
        scopes=(A,),
        expected=frozenset({A, B, C, D}),
    ),
    _Case(
        name="a terminal dependency cuts the walk",
        nodes={A: _Node((B,)), B: _Node((C,), state="complete"), C: _Node()},
        scopes=(A,),
        expected=frozenset({A}),
    ),
    _Case(
        name="a failed dependency cuts the walk",
        nodes={A: _Node((B,)), B: _Node((C,), state="failed"), C: _Node()},
        scopes=(A,),
        expected=frozenset({A}),
    ),
    _Case(
        name="a parked dependency carries the walk",
        nodes={A: _Node((B,)), B: _Node((C,), state="parked"), C: _Node()},
        scopes=(A,),
        expected=frozenset({A, B, C}),
    ),
    _Case(
        name="a terminal starting scope reaches nothing",
        nodes={A: _Node((B,), state="complete"), B: _Node()},
        scopes=(A,),
        expected=frozenset(),
    ),
    _Case(
        name="a scope left out is reached only as a dependency",
        nodes={A: _Node((B,)), B: _Node(), C: _Node((D,)), D: _Node()},
        scopes=(A,),
        expected=frozenset({A, B}),
    ),
    _Case(
        name="a dependency with no node ends that path",
        nodes={A: _Node((E,))},
        scopes=(A,),
        expected=frozenset({A}),
    ),
    _Case(
        name="a starting scope with no node reaches nothing",
        nodes={A: _Node()},
        scopes=(E,),
        expected=frozenset(),
    ),
)

_CLOSURE_CASES = (
    _Case(
        name="a running root carries the walk to its dependencies",
        nodes={A: _Node((B,), state="running"), B: _Node()},
        scopes=(A,),
        expected=frozenset({A, B}),
    ),
)

_NEEDED_CASES = (
    _Case(
        name="a running node keeps none of its dependencies alive",
        nodes={A: _Node((B,), state="running"), B: _Node((C,)), C: _Node()},
        scopes=(A,),
        expected=frozenset(),
    ),
    _Case(
        name="a running node that live work needs carries the walk",
        nodes={A: _Node((B,), state="waiting_deps"), B: _Node((C,), state="running"), C: _Node()},
        scopes=(A, B),
        expected=frozenset({A, B, C}),
    ),
)


_CLOSURE_TABLE = _SHARED_CASES + _CLOSURE_CASES
_NEEDED_TABLE = _SHARED_CASES + _NEEDED_CASES


@pytest.mark.parametrize("case", _CLOSURE_TABLE, ids=[case.name for case in _CLOSURE_TABLE])
def test_dependency_closure(case: _Case) -> None:
    assert dependency_closure(case.nodes, case.scopes) == case.expected


@pytest.mark.parametrize("case", _NEEDED_TABLE, ids=[case.name for case in _NEEDED_TABLE])
def test_needed_scopes(case: _Case) -> None:
    assert needed_scopes(case.nodes, case.scopes) == case.expected
