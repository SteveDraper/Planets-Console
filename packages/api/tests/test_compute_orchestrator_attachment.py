"""Per-orchestrator attachment slot."""

from __future__ import annotations

from api.compute.orchestrator import ComputeOrchestrator


class _Counter:
    def __init__(self) -> None:
        self.count = 0


class _OtherCounter(_Counter):
    pass


def test_attachment_returns_one_instance_per_type_per_orchestrator():
    orchestrator = ComputeOrchestrator(compute_registry={})

    first = orchestrator.attachment(_Counter)
    first.count += 1

    assert orchestrator.attachment(_Counter) is first
    assert orchestrator.attachment(_Counter).count == 1
    assert orchestrator.attachment(_OtherCounter) is not first


def test_attachments_are_not_shared_between_orchestrators():
    first = ComputeOrchestrator(compute_registry={})
    second = ComputeOrchestrator(compute_registry={})

    assert first.attachment(_Counter) is not second.attachment(_Counter)
