"""Test helpers that give a queue-only pool item the node it was dispatched from."""

from __future__ import annotations

from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.pools import ComputeWorkerPool, PoolWorkItem
from api.compute.priority_band import ComputeRequestBand
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen


def publish_queued_node_band(
    orchestrator: ComputeOrchestrator,
    scope: ComputeScope,
    standing_band: ComputeRequestBand,
) -> None:
    """Register a never-executing ``running`` node at ``scope`` and run a dispatch pass.

    That is the state the node of a queued pool item is in, so the pass derives
    ``standing_band`` for it and pool picks rank the item at that band. A scope
    that already has a node raises its band through an attaching request instead.
    """
    _register_running_node(orchestrator, scope, standing_band, execution_generation=0)


def enqueue_held_item(
    pool: ComputeWorkerPool,
    item: PoolWorkItem,
    standing_band: ComputeRequestBand = "background",
) -> None:
    """Queue ``item`` behind a never-executing ``running`` node of its execution.

    The node is the one a real dispatch would have left, so single-step treats
    the item as live work of its scope and pool picks rank it at ``standing_band``.
    """
    orchestrator = pool._lookup_orchestrator(item.orchestrator_id)
    if orchestrator is None:
        raise ValueError(f"orchestrator {item.orchestrator_id} is not registered with the pool")
    _register_running_node(
        orchestrator,
        item.scope,
        standing_band,
        execution_generation=item.execution_generation,
    )
    pool.enqueue_for_tests(item)


def _register_running_node(
    orchestrator: ComputeOrchestrator,
    scope: ComputeScope,
    standing_band: ComputeRequestBand,
    *,
    execution_generation: int,
) -> None:
    if scope in orchestrator.nodes:
        raise ValueError(f"{scope!r} already has a node; attach a request to raise its band")
    orchestrator._nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        standing_band=standing_band,
        execution_generation=execution_generation,
        submission_open=SubmissionOpen(),
    )
    orchestrator.dispatch_ready_work()
