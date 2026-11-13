"""Unit table for the dependency closure the compute DAG keeps alive."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest
from api.compute.dag_reach import needed_scopes
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
    alive: tuple[ComputeScope, ...]
    expected: frozenset[ComputeScope]


_CASES = (
    _Case(
        name="no alive scope reaches nothing",
        nodes={A: _Node((B,)), B: _Node()},
        alive=(),
        expected=frozenset(),
    ),
    _Case(
        name="a chain is reached through every hop",
        nodes={A: _Node((B,)), B: _Node((C,)), C: _Node()},
        alive=(A,),
        expected=frozenset({A, B, C}),
    ),
    _Case(
        name="a chain is reached only below the alive scope",
        nodes={A: _Node((B,)), B: _Node((C,)), C: _Node()},
        alive=(B,),
        expected=frozenset({B, C}),
    ),
    _Case(
        name="a diamond reaches its shared dependency once",
        nodes={A: _Node((B, C)), B: _Node((D,)), C: _Node((D,)), D: _Node()},
        alive=(A,),
        expected=frozenset({A, B, C, D}),
    ),
    _Case(
        name="a terminal dependency cuts the walk",
        nodes={A: _Node((B,)), B: _Node((C,), state="complete"), C: _Node()},
        alive=(A,),
        expected=frozenset({A}),
    ),
    _Case(
        name="a failed dependency cuts the walk",
        nodes={A: _Node((B,)), B: _Node((C,), state="failed"), C: _Node()},
        alive=(A,),
        expected=frozenset({A}),
    ),
    _Case(
        name="a parked dependency carries the walk",
        nodes={A: _Node((B,)), B: _Node((C,), state="parked"), C: _Node()},
        alive=(A,),
        expected=frozenset({A, B, C}),
    ),
    _Case(
        name="a terminal alive scope keeps nothing alive",
        nodes={A: _Node((B,), state="complete"), B: _Node()},
        alive=(A,),
        expected=frozenset(),
    ),
    _Case(
        name="a scope left out of alive is reached only as a dependency",
        nodes={A: _Node((B,)), B: _Node(), C: _Node((D,)), D: _Node()},
        alive=(A,),
        expected=frozenset({A, B}),
    ),
    _Case(
        name="a dependency with no node ends that path",
        nodes={A: _Node((E,))},
        alive=(A,),
        expected=frozenset({A}),
    ),
    _Case(
        name="an alive scope with no node keeps nothing alive",
        nodes={A: _Node()},
        alive=(E,),
        expected=frozenset(),
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=[case.name for case in _CASES])
def test_needed_scopes(case: _Case) -> None:
    assert needed_scopes(case.nodes, case.alive) == case.expected
