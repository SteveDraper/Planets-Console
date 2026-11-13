"""Settling in-flight work: the selection, the dispositions and the needed exemption."""

from __future__ import annotations

from dataclasses import dataclass

from api.compute.in_flight_settle import (
    GameWork,
    InFlightCandidate,
    InFlightSettlePolicy,
    PlayerWork,
    RunningDisposition,
    UnstartedDisposition,
)
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.orchestrator_state import NodeState
from api.compute.running_step import RunningStepDisposition
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.exceptions import DiscardedWorkRefused

_WALK = frozenset({"alpha", "beta"})


@dataclass(frozen=True)
class _SettleEverything(InFlightSettlePolicy):
    """Discards every unstarted candidate and finishes every running one without a stamp."""

    def unstarted(self, candidate: InFlightCandidate) -> UnstartedDisposition:
        return UnstartedDisposition.DISCARD

    def running(self, candidate: InFlightCandidate) -> RunningDisposition:
        return RunningDisposition.FINISH_WITHOUT_STAMP


@dataclass(frozen=True)
class _KeepEverything(InFlightSettlePolicy):
    def unstarted(self, candidate: InFlightCandidate) -> UnstartedDisposition:
        return UnstartedDisposition.KEEP

    def running(self, candidate: InFlightCandidate) -> RunningDisposition:
        return RunningDisposition.KEEP


def _put(
    orchestrator: ComputeOrchestrator,
    analytic_id: str,
    turn: int | str,
    *,
    state: NodeState = "ready",
    perspective: int = 1,
    player_id: int = 7,
    game_id: int = 1,
    dependency_scopes: tuple[ComputeScope, ...] = (),
) -> ComputeScope:
    scope = ComputeScope(
        analytic_id=analytic_id,
        game_id=game_id,
        perspective=perspective,
        turn=turn,
        player_id=player_id,
    )
    orchestrator.nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=dependency_scopes,
        state=state,
        submission_open=SubmissionOpen(),
    )
    if state == "ready":
        orchestrator._ready_queue.append(scope)
    return scope


def _player_work(**overrides: int) -> PlayerWork:
    keys = {"game_id": 1, "perspective": 1, "player_id": 7, **overrides}
    return PlayerWork(analytic_ids=_WALK, **keys)


def test_discard_fails_unstarted_work_and_finish_without_stamp_marks_running_work():
    orchestrator = ComputeOrchestrator(compute_registry={})
    ready = _put(orchestrator, "alpha", 39)
    waiting = _put(orchestrator, "beta", 39, state="waiting_deps")
    parked = _put(orchestrator, "alpha", 37, state="parked")
    running = _put(orchestrator, "alpha", 38, state="running")
    finished = _put(orchestrator, "beta", 38, state="complete")

    orchestrator.settle_in_flight_work(_player_work(), _SettleEverything())

    for discarded in (ready, waiting, parked):
        assert orchestrator.nodes[discarded].state == "failed"
        assert isinstance(orchestrator.nodes[discarded].error, DiscardedWorkRefused)
    assert ready not in orchestrator._ready_queue
    assert orchestrator.nodes[running].state == "running"
    assert orchestrator.nodes[running].running_step is RunningStepDisposition.FINISH_WITHOUT_STAMP
    assert orchestrator.nodes[finished].state == "complete"
    assert orchestrator.nodes[finished].error is None


def test_keep_leaves_unstarted_and_running_work_alone():
    orchestrator = ComputeOrchestrator(compute_registry={})
    ready = _put(orchestrator, "alpha", 39)
    running = _put(orchestrator, "alpha", 38, state="running")

    orchestrator.settle_in_flight_work(_player_work(), _KeepEverything())

    assert orchestrator.nodes[ready].state == "ready"
    assert ready in orchestrator._ready_queue
    assert orchestrator.nodes[running].running_step is RunningStepDisposition.CONTINUE


def test_player_work_selects_one_players_concrete_turns_of_its_analytics():
    orchestrator = ComputeOrchestrator(compute_registry={})
    selected = _put(orchestrator, "alpha", 39)
    other_analytic = _put(orchestrator, "gamma", 39)
    other_player = _put(orchestrator, "alpha", 39, player_id=8)
    other_perspective = _put(orchestrator, "alpha", 39, perspective=2)
    other_game = _put(orchestrator, "alpha", 39, game_id=2)
    wildcard_turn = _put(orchestrator, "alpha", "*")

    orchestrator.settle_in_flight_work(_player_work(), _SettleEverything())

    assert orchestrator.nodes[selected].state == "failed"
    for untouched in (other_analytic, other_player, other_perspective, other_game, wildcard_turn):
        assert orchestrator.nodes[untouched].state == "ready"


def test_game_work_spans_perspectives_and_players_of_one_game():
    orchestrator = ComputeOrchestrator(compute_registry={})
    first = _put(orchestrator, "alpha", 39)
    other_perspective = _put(orchestrator, "beta", 39, perspective=2, player_id=3)
    running = _put(orchestrator, "alpha", 38, perspective=3, state="running")
    other_analytic = _put(orchestrator, "gamma", 39)
    other_game = _put(orchestrator, "alpha", 39, game_id=2)

    orchestrator.settle_in_flight_work(
        GameWork(game_id=1, analytic_ids=_WALK),
        _SettleEverything(),
    )

    assert orchestrator.nodes[first].state == "failed"
    assert orchestrator.nodes[other_perspective].state == "failed"
    assert orchestrator.nodes[running].running_step is RunningStepDisposition.FINISH_WITHOUT_STAMP
    assert orchestrator.nodes[other_analytic].state == "ready"
    assert orchestrator.nodes[other_game].state == "ready"


def test_a_discard_that_kept_work_still_needs_is_kept():
    orchestrator = ComputeOrchestrator(compute_registry={})
    needed_hop = _put(orchestrator, "alpha", 38)
    needed_root = _put(orchestrator, "alpha", 39, dependency_scopes=(needed_hop,))
    outside = _put(
        orchestrator,
        "gamma",
        40,
        state="waiting_deps",
        dependency_scopes=(needed_root,),
    )
    unneeded = _put(orchestrator, "beta", 39)

    orchestrator.settle_in_flight_work(_player_work(), _SettleEverything())

    assert orchestrator.nodes[needed_root].state == "ready"
    assert orchestrator.nodes[needed_hop].state == "ready"
    assert orchestrator.nodes[outside].state == "waiting_deps"
    assert orchestrator.nodes[unneeded].state == "failed"


def test_a_discard_needed_only_by_other_discards_is_failed():
    orchestrator = ComputeOrchestrator(compute_registry={})
    hop = _put(orchestrator, "alpha", 38)
    root = _put(orchestrator, "alpha", 39, state="waiting_deps", dependency_scopes=(hop,))

    orchestrator.settle_in_flight_work(_player_work(), _SettleEverything())

    assert isinstance(orchestrator.nodes[hop].error, DiscardedWorkRefused)
    assert orchestrator.nodes[root].state == "failed"


def test_settle_leaves_post_lock_work_for_the_caller_to_drain():
    orchestrator = ComputeOrchestrator(compute_registry={})
    ready = _put(orchestrator, "alpha", 39)
    outcomes: list[ScopeLifecycleSnapshot] = []
    orchestrator.observers.register_scope_outcome_listener(outcomes.append)

    orchestrator.settle_in_flight_work(_player_work(), _SettleEverything())

    assert orchestrator.nodes[ready].state == "failed"
    assert outcomes == []
    orchestrator.observers.drain_post_lock_callbacks()
    assert [outcome.scope for outcome in outcomes] == [ready]
