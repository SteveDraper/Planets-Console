"""Unit tests for ``ComputeNodeRun`` state predicates."""

from __future__ import annotations

from api.compute.orchestrator_state import ComputeNodeRun, NodeState
from api.compute.scope import ComputeScope

_SCOPE = ComputeScope(analytic_id="fleet", game_id=1)


def _node(state: NodeState) -> ComputeNodeRun:
    return ComputeNodeRun(scope=_SCOPE, dependency_scopes=(), state=state)


def test_is_terminal_true_only_for_complete_and_failed() -> None:
    terminal_states: set[NodeState] = {"complete", "failed"}
    for state in NodeState.__args__:
        assert _node(state).is_terminal == (state in terminal_states), state


def test_parked_is_not_terminal() -> None:
    """Parked is a soft pause -- dependents stay blocked, not released."""
    assert _node("parked").is_terminal is False


def test_blocks_readiness_refresh_covers_terminal_running_and_parked() -> None:
    blocking_states: set[NodeState] = {"complete", "failed", "running", "parked"}
    for state in NodeState.__args__:
        assert _node(state).blocks_readiness_refresh == (state in blocking_states), state


def test_allows_priority_adopt_excludes_terminal_states() -> None:
    adoptable_states: set[NodeState] = {"waiting_deps", "parked", "ready", "running"}
    for state in NodeState.__args__:
        assert _node(state).allows_priority_adopt == (state in adoptable_states), state
