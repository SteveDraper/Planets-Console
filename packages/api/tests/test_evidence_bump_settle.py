"""What a bump's settle does to work a kept running node depended on."""

from __future__ import annotations

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.orchestrator_state import NodeState
from api.compute.running_step import RunningStepDisposition
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.exceptions import DiscardedWorkRefused
from api.services.evidence_bump import discard_bumped_player_work


def _put_fleet(
    orchestrator: ComputeOrchestrator,
    turn: int,
    *,
    state: NodeState,
    dependency_scopes: tuple[ComputeScope, ...] = (),
) -> ComputeScope:
    scope = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=1,
        perspective=1,
        turn=turn,
        player_id=7,
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


def test_bump_discards_a_replaced_dependency_of_a_kept_running_shell_node():
    """A running node's inputs were complete when it was dispatched, so it keeps none alive."""
    orchestrator = ComputeOrchestrator(compute_registry={})
    replaced_prior = _put_fleet(orchestrator, 39, state="ready")
    running_shell = _put_fleet(
        orchestrator, 40, state="running", dependency_scopes=(replaced_prior,)
    )

    discard_bumped_player_work(
        orchestrator,
        game_id=1,
        perspective=1,
        player_id=7,
        shell_turns=frozenset({40}),
        live_turns=frozenset(),
    )

    assert orchestrator.nodes[replaced_prior].state == "failed"
    assert isinstance(orchestrator.nodes[replaced_prior].error, DiscardedWorkRefused)
    assert replaced_prior not in orchestrator._ready_queue
    assert orchestrator.nodes[running_shell].state == "running"
    assert orchestrator.nodes[running_shell].running_step is RunningStepDisposition.CONTINUE
