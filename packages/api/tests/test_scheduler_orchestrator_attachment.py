"""SchedulerOrchestratorAttachment.registered_orchestrator: a read-only view of the registration."""

from __future__ import annotations

from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests
from api.streaming.table_stream.scheduler_orchestrator_attachment import (
    SchedulerOrchestratorAttachment,
)


def _attachment() -> SchedulerOrchestratorAttachment:
    return SchedulerOrchestratorAttachment(
        on_scope_outcome=lambda _outcome: None,
        dispatch_gate=lambda _node: True,
    )


def test_registered_orchestrator_is_none_before_registration() -> None:
    assert _attachment().registered_orchestrator() is None


def test_registered_orchestrator_is_the_orchestrator_callbacks_are_on() -> None:
    attachment = _attachment()

    registered = attachment.ensure_registered()

    assert attachment.registered_orchestrator() is registered
    attachment.shutdown()


def test_registered_orchestrator_is_none_after_shutdown() -> None:
    attachment = _attachment()
    attachment.ensure_registered()

    attachment.shutdown()

    assert attachment.registered_orchestrator() is None


def test_registered_orchestrator_is_none_after_the_singleton_is_replaced() -> None:
    attachment = _attachment()
    attachment.ensure_registered()

    reset_orchestrators_for_tests()
    get_compute_orchestrator()

    assert attachment.registered_orchestrator() is None
    attachment.shutdown()


def test_registered_orchestrator_does_not_register() -> None:
    attachment = _attachment()

    attachment.registered_orchestrator()

    assert attachment.registered_orchestrator() is None
