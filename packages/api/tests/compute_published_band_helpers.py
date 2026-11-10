"""Test helpers that set the band an orchestrator publishes for a scope."""

from __future__ import annotations

from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.priority_band import ComputePriorityBand
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen


def publish_node_band(
    orchestrator: ComputeOrchestrator,
    scope: ComputeScope,
    band: ComputePriorityBand,
) -> None:
    """Set ``scope``'s node to ``band`` and run a dispatch pass so the band is published.

    A scope with no node gets a ``running`` node that never executes. That is
    the state the node of a queued pool item is in, so pool picks rank that
    item at ``band``.
    """
    node = orchestrator.nodes.get(scope)
    if node is None:
        node = ComputeNodeRun(
            scope=scope,
            dependency_scopes=(),
            state="running",
            submission_open=SubmissionOpen(),
        )
        orchestrator._nodes[scope] = node
    node.priority_band = band
    orchestrator.dispatch_ready_work()
