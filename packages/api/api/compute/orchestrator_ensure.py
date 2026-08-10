"""Orchestration-plane ensure: satisfied short-circuit or submit+wait."""

from __future__ import annotations

from dataclasses import replace
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
        Otherwise submits with ``force_fresh`` (when the caller did not already
        set it) and waits until the scope is terminal or ``timeout``. Force-fresh
        on the unsatisfied path replaces hollow terminal nodes left after wipe /
        invalidate so ensure cannot attach to a stale ``complete``.

        Defaults match grill locks: cold ensure → ``interactive_ensure`` priority.
        Pool workers and leaf ``run_step`` must never call this.
        """
        bundle = self._require_bundle(request)
        ctx = self._ctx_for_bundle(bundle)
        registration = self._compute_registry[request.scope.analytic_id]
        already_satisfied = registration.persistence_policy.is_satisfied(
            ctx,
            request.scope,
        )

        if already_satisfied:
            handle = self.submit(request)
            if handle._node.is_terminal:
                error = handle.error
                if error is not None:
                    raise error
                return handle
            return handle.wait(timeout=timeout)

        ensure_request = request if request.force_fresh else replace(request, force_fresh=True)
        return self.submit(ensure_request).wait(timeout=timeout)
