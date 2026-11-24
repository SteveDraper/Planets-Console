"""A drain on a thread that is already draining leaves its work to that drain.

An inline dependency chain advances through post-lock callbacks: each node's
finish schedules the next dispatch pass, and each hand-off drains. Those
drains nest on one thread. A nested drain returns at once and the active
drain's loop runs what it would have, so stack depth stays the same however
long the chain is.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import replace

import pytest
from api.compute import ComputeOrchestrator, ComputeRequest, build_compute_registry
from api.compute.orchestrator_observers import OrchestratorObservers
from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery

from tests.compute_orchestrator_fixtures import (
    RecordingPersistencePolicy,
    inline_compute_registration,
    make_compute_scope,
    make_export_scope,
)
from tests.fixtures.export_framework.chain_exports import CHAIN_ID
from tests.fixtures.export_framework.harness import (
    CHAIN_FIXTURE_EXPORT_REGISTRY,
    build_stored_turn_chain,
    make_fixture_query_context,
)

# Well past the length at which per-node recursion overflowed the default limit.
LONG_CHAIN_TURNS = 600
# Frames a chain may add below the test's own frame, whatever its length.
MAX_CHAIN_STACK_FRAMES = 120
# Short enough that a chain the orchestrator strands fails the test promptly.
CHAIN_ENSURE_TIMEOUT_SEC = 30.0
# Each recovery nests a submit drain inside a post-lock callback, so per-node
# recursion overflowed the default limit by 20 turns. 1.5x that still overflows
# it, and stays fast: this chain's cost grows much faster than its length.
RECOVERY_CHAIN_TURNS = 30


def _stack_depth() -> int:
    depth = 0
    frame = sys._getframe(1)
    while frame is not None:
        depth += 1
        frame = frame.f_back
    return depth


class _DeepestStack:
    """Records the deepest stack seen by ``sample``."""

    def __init__(self) -> None:
        self.deepest = 0

    def sample(self) -> None:
        self.deepest = max(self.deepest, _stack_depth())


def _chain_ctx_and_scope(sample_turn, turns: int):
    stored = build_stored_turn_chain(sample_turn, through_turn=turns)
    ctx = make_fixture_query_context(
        stored[turns],
        stored_turns=stored,
        registry=CHAIN_FIXTURE_EXPORT_REGISTRY,
        enforce_inline_ensure_threshold=False,
    )
    return ctx, make_compute_scope(CHAIN_ID, make_export_scope(stored[turns]))


def _chain_orchestrator(stack: _DeepestStack, persistence_policy=None) -> ComputeOrchestrator:
    """An inline chain whose step samples the stack each time it runs."""
    registration = inline_compute_registration(CHAIN_ID)

    def run_step(job):
        stack.sample()
        return {"result": job["scope"]}

    registration = replace(registration, run_steps=(("materialize", run_step),))
    if persistence_policy is not None:
        registration = replace(registration, persistence_policy=persistence_policy)
    return ComputeOrchestrator(compute_registry=build_compute_registry((registration,)))


def _ensure_chain(orchestrator: ComputeOrchestrator, ctx, scope) -> None:
    handle = orchestrator.ensure_scope(
        ComputeRequest(ctx=ctx, scope=scope), timeout=CHAIN_ENSURE_TIMEOUT_SEC
    )
    assert handle.state == "complete"


def test_a_long_inline_chain_completes_without_growing_the_stack(sample_turn):
    ctx, scope = _chain_ctx_and_scope(sample_turn, LONG_CHAIN_TURNS)
    stack = _DeepestStack()
    orchestrator = _chain_orchestrator(stack)
    orchestrator.observers.register_scope_outcome_listener(lambda _snapshot: stack.sample())
    base = _stack_depth()

    _ensure_chain(orchestrator, ctx, scope)

    assert len(orchestrator.nodes) == LONG_CHAIN_TURNS
    assert all(node.state == "complete" for node in orchestrator.nodes.values())
    assert stack.deepest - base < MAX_CHAIN_STACK_FRAMES


class _DefersOncePerScopePolicy(RecordingPersistencePolicy):
    """Defers each scope's first persist until its previous turn is recreated."""

    def __init__(self) -> None:
        super().__init__()
        self.deferred_scopes: set = set()

    def persist(self, ctx, scope, result_wire) -> None:
        if scope.turn > 1 and scope not in self.deferred_scopes:
            self.deferred_scopes.add(scope)
            raise PersistDeferredError(
                "previous turn must re-close",
                recovery=PersistDependencyRecovery(
                    dependency_scope=replace(scope, turn=scope.turn - 1),
                    step_kind="materialize",
                ),
            )
        super().persist(ctx, scope, result_wire)


def test_a_chain_whose_every_persist_defers_once_completes_without_growing_the_stack(
    sample_turn,
):
    """Each recovery submits from inside a post-lock callback, nesting a drain."""
    ctx, scope = _chain_ctx_and_scope(sample_turn, RECOVERY_CHAIN_TURNS)
    stack = _DeepestStack()
    policy = _DefersOncePerScopePolicy()
    orchestrator = _chain_orchestrator(stack, persistence_policy=policy)
    base = _stack_depth()

    _ensure_chain(orchestrator, ctx, scope)

    assert len(policy.deferred_scopes) == RECOVERY_CHAIN_TURNS - 1
    assert stack.deepest - base < MAX_CHAIN_STACK_FRAMES


def test_a_listener_that_dispatches_adds_one_bounded_level(sample_turn):
    ctx, scope = _chain_ctx_and_scope(sample_turn, LONG_CHAIN_TURNS)
    stack = _DeepestStack()
    orchestrator = _chain_orchestrator(stack)

    def dispatch_on_each_outcome(_snapshot) -> None:
        orchestrator.dispatch_ready_work()
        stack.sample()

    orchestrator.observers.register_scope_outcome_listener(dispatch_on_each_outcome)
    base = _stack_depth()

    _ensure_chain(orchestrator, ctx, scope)

    assert stack.deepest - base < MAX_CHAIN_STACK_FRAMES


def test_a_drain_of_one_orchestrator_does_not_defer_another(sample_turn):
    """A callback on one orchestrator that submits to another sees that work finish."""
    ctx, scope = _chain_ctx_and_scope(sample_turn, 3)
    outer = _chain_orchestrator(_DeepestStack())
    inner = _chain_orchestrator(_DeepestStack())
    inner_states: list[str] = []

    def submit_to_the_other_orchestrator() -> None:
        handle = inner.submit(ComputeRequest(ctx=ctx, scope=scope))
        inner_states.append(handle.state)

    with outer.observers.condition:
        outer.observers.schedule_post_lock(submit_to_the_other_orchestrator)
    outer.drain_post_lock_callbacks()

    assert inner_states == ["complete"]


class _DrainEscape(BaseException):
    """Escapes a drain's containment, which catches ``Exception`` only."""


def test_a_drain_that_unwinds_requeues_its_unstarted_callbacks_ahead_of_later_ones():
    condition = threading.Condition()
    observers = OrchestratorObservers(condition)
    ran: list[str] = []

    def escape() -> None:
        ran.append("escape")
        raise _DrainEscape

    with condition:
        observers.schedule_post_lock(lambda: ran.append("first"))
        observers.schedule_post_lock(escape)
        observers.schedule_post_lock(lambda: ran.append("unstarted-1"))
        observers.schedule_post_lock(lambda: ran.append("unstarted-2"))

    with pytest.raises(_DrainEscape):
        observers.drain_post_lock_callbacks()
    with condition:
        observers.schedule_post_lock(lambda: ran.append("later"))
    observers.drain_post_lock_callbacks()

    assert ran == ["first", "escape", "unstarted-1", "unstarted-2", "later"]


def test_a_nested_drain_returns_and_the_active_drain_runs_its_work():
    condition = threading.Condition()
    observers = OrchestratorObservers(condition)
    ran: list[str] = []

    def schedule_and_drain() -> None:
        with condition:
            observers.schedule_post_lock(lambda: ran.append("scheduled by the callback"))
        observers.drain_post_lock_callbacks()
        ran.append("nested drain returned")

    with condition:
        observers.schedule_post_lock(schedule_and_drain)
    observers.drain_post_lock_callbacks()

    assert ran == ["nested drain returned", "scheduled by the callback"]


def test_a_node_readmitted_inside_a_drain_is_not_terminal_for_callbacks_queued_before_its_pass(
    sample_turn,
):
    """Scores relies on this to ignore an old execution's outcome after a re-admit.

    The re-admit registers the new node in its own lock hold and queues its
    pass, so a callback queued earlier in the drain still sees it unstarted.
    """
    ctx, scope = _chain_ctx_and_scope(sample_turn, 1)
    orchestrator = _chain_orchestrator(_DeepestStack())
    _ensure_chain(orchestrator, ctx, scope)
    seen_by_earlier_callback: list[str] = []

    def readmit() -> None:
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope, force_fresh=True))

    with orchestrator.observers.condition:
        orchestrator.observers.schedule_post_lock(readmit)
        orchestrator.observers.schedule_post_lock(
            lambda: seen_by_earlier_callback.append(orchestrator.nodes[scope].state)
        )
    orchestrator.drain_post_lock_callbacks()

    assert seen_by_earlier_callback == ["ready"]
    assert orchestrator.nodes[scope].state == "complete"
