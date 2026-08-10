"""Orchestration-plane ensure for export scopes (#204).

Designated in-process callers submit the query root through the compute
orchestrator and wait. Pool workers and leaf ``run_step`` / job-wire builders
must not call these helpers.
"""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.compute.constants import ENSURE_WAIT_TIMEOUT_SEC
from api.compute.orchestrator_state import ComputeRequest
from api.compute.pools import ComputePriorityBand
from api.compute.scope import normalize_export_scope_to_compute_scope


def analytic_has_compute_registration(analytic_id: str) -> bool:
    """Return whether ``analytic_id`` is registered on the process compute registry."""
    from api.compute.registry import COMPUTE_REGISTRY

    return analytic_id in COMPUTE_REGISTRY


def ensure_export_scope_via_orchestrator(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    *,
    priority_band: ComputePriorityBand = "interactive_ensure",
    force_fresh: bool = False,
    timeout: float | None = ENSURE_WAIT_TIMEOUT_SEC,
) -> bool:
    """Bring one export scope to durable satisfaction via orchestrator submit+wait.

    Returns whether ``PersistencePolicy.is_satisfied`` holds after ensure.
    """
    from api.compute.registry import COMPUTE_REGISTRY
    from api.compute.runtime import get_compute_orchestrator

    registration = COMPUTE_REGISTRY.get(analytic_id)
    if registration is None:
        raise RuntimeError(
            f"cannot ensure {analytic_id!r} via orchestrator: analytic is not in COMPUTE_REGISTRY"
        )
    compute_scope = normalize_export_scope_to_compute_scope(
        scope,
        analytic_id=analytic_id,
        scope_key_spec=registration.scope_key_spec,
    )
    orchestrator = get_compute_orchestrator()
    orchestrator.ensure_scope(
        ComputeRequest(
            scope=compute_scope,
            ctx=ctx,
            priority_band=priority_band,
            force_fresh=force_fresh,
        ),
        timeout=timeout,
    )
    return registration.persistence_policy.is_satisfied(ctx, compute_scope)
