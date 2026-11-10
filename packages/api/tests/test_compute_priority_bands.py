"""Unit table for the pure priority band derivation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest
from api.compute.orchestrator_state import TERMINAL_NODE_STATES, NodeState
from api.compute.priority_band import (
    PRIORITY_BAND_RANK,
    UNWATCHED,
    ComputePriorityBand,
    ComputeRequestBand,
    ShellStreamWatch,
    WatchedShellKey,
    derive_priority_bands,
    highest_band,
)
from api.compute.profile import AnalyticComputeProfile
from api.compute.registry import AnalyticComputeRegistration
from api.compute.root_plan import open_ignored_root_plan
from api.compute.scope import WILDCARD, ComputeScope, ScopeAxisValue, ScopeKeySpec

from tests.test_compute_foundation import _StubPersistencePolicy

GAME_ID = 628580
PERSPECTIVE = 1


class _StubWatch(ShellStreamWatch):
    """A distinct watch identity; the derivation reads the snapshot it is handed."""

    def watched_keys(self) -> frozenset[WatchedShellKey]:
        return frozenset()


WALK_WATCH = _StubWatch()
OTHER_WATCH = _StubWatch()


@dataclass
class _Node:
    dependency_scopes: tuple[ComputeScope, ...] = ()
    standing_band: ComputeRequestBand = "background"
    state: NodeState = "ready"

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_NODE_STATES


def _scope(
    analytic_id: str,
    turn: ScopeAxisValue,
    player_id: ScopeAxisValue = 3,
) -> ComputeScope:
    return ComputeScope(
        analytic_id=analytic_id,
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn=turn,
        player_id=player_id,
    )


def _key(turn: int, player_id: int = 3) -> WatchedShellKey:
    return WatchedShellKey(game_id=GAME_ID, perspective=PERSPECTIVE, turn=turn, player_id=player_id)


def _registration(analytic_id: str, watch: ShellStreamWatch) -> AnalyticComputeRegistration:
    return AnalyticComputeRegistration(
        analytic_id=analytic_id,
        scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
        compute_profile=AnalyticComputeProfile(steps=()),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wire={},
        run_step={},
        open_root_plan=open_ignored_root_plan,
        shell_stream_watch=watch,
    )


REGISTRY: Mapping[str, AnalyticComputeRegistration] = {
    "walk": _registration("walk", WALK_WATCH),
    "other": _registration("other", OTHER_WATCH),
    "plain": _registration("plain", UNWATCHED),
}

W8 = _scope("walk", 8)
W9 = _scope("walk", 9)
W10 = _scope("walk", 10)
O10 = _scope("other", 10)
P10 = _scope("plain", 10)


@dataclass(frozen=True)
class _Case:
    id: str
    nodes: dict[ComputeScope, _Node]
    walk_keys: frozenset[WatchedShellKey]
    expected: dict[ComputeScope, ComputePriorityBand]
    other_keys: frozenset[WatchedShellKey] = frozenset()


CASES = [
    _Case(
        id="standing band when nothing depends on the node",
        nodes={
            W8: _Node(standing_band="interactive_ensure"),
            W9: _Node(),
        },
        walk_keys=frozenset(),
        expected={W8: "interactive_ensure", W9: "background"},
    ),
    _Case(
        id="standing max over the node and its dependents",
        nodes={
            W8: _Node(standing_band="interactive_ensure"),
            W9: _Node(dependency_scopes=(W8,)),
            W10: _Node(dependency_scopes=(W8,), standing_band="interactive_ensure"),
        },
        walk_keys=frozenset(),
        expected={W8: "interactive_ensure", W9: "background", W10: "interactive_ensure"},
    ),
    _Case(
        id="a dependent's standing band propagates through a chain",
        nodes={
            W8: _Node(),
            W9: _Node(dependency_scopes=(W8,)),
            W10: _Node(dependency_scopes=(W9,), standing_band="interactive_ensure"),
        },
        walk_keys=frozenset(),
        expected={W8: "interactive_ensure", W9: "interactive_ensure", W10: "interactive_ensure"},
    ),
    _Case(
        id="a watched dependent makes its transitive dependencies stream_attached",
        nodes={
            W8: _Node(standing_band="interactive_ensure"),
            W9: _Node(dependency_scopes=(W8,)),
            W10: _Node(dependency_scopes=(W9,)),
        },
        walk_keys=frozenset({_key(10)}),
        expected={W8: "stream_attached", W9: "stream_attached", W10: "stream_attached"},
    ),
    _Case(
        id="a watched node does not raise its own dependents",
        nodes={
            W8: _Node(),
            W9: _Node(dependency_scopes=(W8,)),
            W10: _Node(dependency_scopes=(W9,)),
        },
        walk_keys=frozenset({_key(9)}),
        expected={W8: "stream_attached", W9: "stream_attached", W10: "background"},
    ),
    _Case(
        id="parked dependents count",
        nodes={
            W8: _Node(state="waiting_deps"),
            W9: _Node(dependency_scopes=(W8,), state="parked"),
            W10: _Node(dependency_scopes=(W9,), state="parked"),
        },
        walk_keys=frozenset({_key(10)}),
        expected={W8: "stream_attached", W9: "stream_attached", W10: "stream_attached"},
    ),
    _Case(
        id="a key applies only to nodes registered with the watch it came from",
        nodes={
            W8: _Node(),
            O10: _Node(dependency_scopes=(W8,)),
            P10: _Node(dependency_scopes=(W8,)),
        },
        walk_keys=frozenset({_key(10)}),
        expected={W8: "background", O10: "background", P10: "background"},
    ),
    _Case(
        id="another watch's key raises its own nodes and their dependencies",
        nodes={
            W8: _Node(),
            O10: _Node(dependency_scopes=(W8,)),
        },
        walk_keys=frozenset(),
        other_keys=frozenset({_key(10)}),
        expected={W8: "stream_attached", O10: "stream_attached"},
    ),
    _Case(
        id="terminal nodes are excluded and do not propagate",
        nodes={
            W8: _Node(),
            W9: _Node(dependency_scopes=(W8,), state="complete"),
            W10: _Node(dependency_scopes=(W9,), standing_band="interactive_ensure"),
        },
        walk_keys=frozenset({_key(9)}),
        expected={W8: "background", W10: "interactive_ensure"},
    ),
    _Case(
        id="a terminal dependency is excluded from the result",
        nodes={
            W8: _Node(state="failed"),
            W9: _Node(dependency_scopes=(W8,)),
        },
        walk_keys=frozenset({_key(8), _key(9)}),
        expected={W9: "stream_attached"},
    ),
    _Case(
        id="a dependency scope with no node is ignored",
        nodes={W9: _Node(dependency_scopes=(W8,))},
        walk_keys=frozenset({_key(9)}),
        expected={W9: "stream_attached"},
    ),
    _Case(
        id="a wildcard player is never watched",
        nodes={_scope("walk", 9, WILDCARD): _Node()},
        walk_keys=frozenset({_key(9)}),
        expected={_scope("walk", 9, WILDCARD): "background"},
    ),
    _Case(
        id="a non-int turn is never watched",
        nodes={_scope("walk", WILDCARD): _Node()},
        walk_keys=frozenset({_key(9)}),
        expected={_scope("walk", WILDCARD): "background"},
    ),
    _Case(
        id="a key for another player does not match",
        nodes={W9: _Node()},
        walk_keys=frozenset({_key(9, player_id=4)}),
        expected={W9: "background"},
    ),
    _Case(
        id="a shared dependency takes the highest band of its dependents",
        nodes={
            W8: _Node(),
            W9: _Node(dependency_scopes=(W8,), standing_band="interactive_ensure"),
            W10: _Node(dependency_scopes=(W8,)),
        },
        walk_keys=frozenset({_key(10)}),
        expected={W8: "stream_attached", W9: "interactive_ensure", W10: "stream_attached"},
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_derive_priority_bands(case: _Case) -> None:
    watched = {
        WALK_WATCH: case.walk_keys,
        OTHER_WATCH: case.other_keys,
        UNWATCHED: frozenset(),
    }

    bands = derive_priority_bands(case.nodes, watched, REGISTRY)

    assert dict(bands) == case.expected


def test_derived_bands_are_read_only() -> None:
    bands = derive_priority_bands(
        {W8: _Node()},
        {WALK_WATCH: frozenset(), OTHER_WATCH: frozenset(), UNWATCHED: frozenset()},
        REGISTRY,
    )

    with pytest.raises(TypeError):
        bands[W9] = "background"  # type: ignore[index]


def test_unwatched_has_no_keys() -> None:
    assert UNWATCHED.watched_keys() == frozenset()


@pytest.mark.parametrize(
    ("bands", "expected"),
    [
        (("background",), "background"),
        (("background", "interactive_ensure"), "interactive_ensure"),
        (("interactive_ensure", "stream_attached", "background"), "stream_attached"),
    ],
)
def test_highest_band(
    bands: tuple[ComputePriorityBand, ...], expected: ComputePriorityBand
) -> None:
    assert highest_band(*bands) == expected


def test_band_rank_orders_stream_first() -> None:
    assert sorted(PRIORITY_BAND_RANK, key=PRIORITY_BAND_RANK.__getitem__) == [
        "stream_attached",
        "interactive_ensure",
        "background",
    ]
