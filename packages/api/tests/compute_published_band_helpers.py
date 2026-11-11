"""Test helper that gives a queue-only pool item a node with a standing band."""

from __future__ import annotations

from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
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
    if scope in orchestrator.nodes:
        raise ValueError(f"{scope!r} already has a node; attach a request to raise its band")
    orchestrator._nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        standing_band=standing_band,
        submission_open=SubmissionOpen(),
    )
    orchestrator.dispatch_ready_work()
