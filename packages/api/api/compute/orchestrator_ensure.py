"""Orchestration-plane ensure: satisfied short-circuit or submit+wait."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.compute.constants import ENSURE_WAIT_TIMEOUT_SEC
from api.compute.orchestrator_state import ComputeHandle, ComputeRequest

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator


class OrchestratorEnsureMixin:
    """Public ensure entry for designated in-process callers (#204)."""

    def ensure_scope(
        self: ComputeOrchestrator,
        request: ComputeRequest,
        *,
        timeout: float | None = ENSURE_WAIT_TIMEOUT_SEC,
    ) -> ComputeHandle:
        """Bring ``request.scope`` to terminal quality on the orchestration plane.

        If durable satisfaction already holds, returns a terminal handle without
        blocking on pool work (submit may still short-circuit to ``complete``).
        Otherwise submits and waits until the scope is terminal or ``timeout``.

        Defaults match grill locks: callers typically pass ``force_fresh=False``
        and an inherited ``priority_band`` (cold ensure → ``interactive_ensure``).
        Pool workers and leaf ``run_step`` must never call this.
        """
        bundle = self._require_bundle(request)
        ctx = self._ctx_for_bundle(bundle)
        registration = self._compute_registry[request.scope.analytic_id]
        already_satisfied = registration.persistence_policy.is_satisfied(
            ctx,
            request.scope,
        )

        handle = self.submit(request)
        if already_satisfied and handle._node.is_terminal:
            error = handle.error
            if error is not None:
                raise error
            return handle
        return handle.wait(timeout=timeout)
