"""Orchestration-plane ensure for export scopes (#204).

Designated in-process callers submit the query root through the compute
orchestrator and wait. Pool workers and leaf ``run_step`` / job-wire builders
must not call these helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.compute.constants import ENSURE_WAIT_TIMEOUT_SEC
from api.compute.orchestrator_state import ComputeRequest
from api.compute.pools import ComputePriorityBand
from api.compute.scope import ComputeScope, normalize_export_scope_to_compute_scope

if TYPE_CHECKING:
    from api.analytics.exports.catalog import AnalyticExportCatalog
    from api.compute.registry import AnalyticComputeRegistration

HatchReadClassification = Literal["final", "in_progress", "needs_ensure"]


def analytic_has_compute_registration(analytic_id: str) -> bool:
    """Return whether ``analytic_id`` is registered on the process compute registry."""
    from api.compute.registry import COMPUTE_REGISTRY

    return analytic_id in COMPUTE_REGISTRY


def _registered_compute_scope(
    analytic_id: str,
    scope: ExportScope,
) -> tuple[AnalyticComputeRegistration, ComputeScope] | None:
    from api.compute.registry import COMPUTE_REGISTRY

    registration = COMPUTE_REGISTRY.get(analytic_id)
    if registration is None:
        return None
    compute_scope = normalize_export_scope_to_compute_scope(
        scope,
        analytic_id=analytic_id,
        scope_key_spec=registration.scope_key_spec,
    )
    return registration, compute_scope


def export_scope_is_ensure_final(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    catalog: AnalyticExportCatalog,
) -> bool:
    """True when hatch-read may materialize: persisted / ensure-final.

    Compute-registered analytics use ``PersistencePolicy.is_satisfied`` (scores:
    turn-evidence closed; fleet: ``has_final_ledger``). Fixture catalogs use
    ``is_persisted``. Stronger than ``is_export_scope_ensure_satisfied``, which
    is the admit-skip gate (true for an in-flight scores ``RowRun``).
    """
    try:
        resolved = _registered_compute_scope(analytic_id, scope)
    except ValueError:
        return False
    if resolved is not None:
        registration, compute_scope = resolved
        return registration.persistence_policy.is_satisfied(ctx, compute_scope)
    if catalog.is_persisted is None:
        return False
    return catalog.is_persisted(ctx, scope)


def export_scope_has_nonterminal_work(analytic_id: str, scope: ExportScope) -> bool:
    """True when the compute orchestrator holds nonterminal work for ``scope``."""
    from api.compute.runtime import get_compute_orchestrator

    try:
        resolved = _registered_compute_scope(analytic_id, scope)
    except ValueError:
        return False
    if resolved is None:
        return False
    _, compute_scope = resolved
    return get_compute_orchestrator().has_nonterminal_scope_work(compute_scope)


def classify_hatch_read_scope(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    catalog: AnalyticExportCatalog,
) -> HatchReadClassification:
    """Classify hatch-read readiness with one predicate order.

    Ensure-final materializes as ``ok``. Otherwise not-yet-final work (catalog
    ``is_in_progress`` or orchestrator nonterminal) is ``in_progress``.
    Un-normalizable compute scope and missing work are ``needs_ensure``.
    """
    try:
        _registered_compute_scope(analytic_id, scope)
    except ValueError:
        return "needs_ensure"

    if export_scope_is_ensure_final(ctx, analytic_id, scope, catalog):
        return "final"
    if catalog.is_in_progress is not None and catalog.is_in_progress(ctx, scope):
        return "in_progress"
    if export_scope_has_nonterminal_work(analytic_id, scope):
        return "in_progress"
    return "needs_ensure"


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

    Submits with the caller's ``force_fresh`` (default ``False`` per F1). Returns
    whether ``PersistencePolicy.is_satisfied`` holds after ensure.
    """
    from api.compute.runtime import get_compute_orchestrator

    resolved = _registered_compute_scope(analytic_id, scope)
    if resolved is None:
        raise RuntimeError(
            f"cannot ensure {analytic_id!r} via orchestrator: analytic is not in COMPUTE_REGISTRY"
        )
    registration, compute_scope = resolved
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
