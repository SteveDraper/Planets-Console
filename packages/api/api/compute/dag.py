"""DAG planning for compute orchestrator from ENSURE_DEPENDENCIES."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_dependency_walk import (
    dependency_scope_for,
    ensure_dependency_turn_floor,
    walk_dependency_tree,
)
from api.analytics.export_types import ExportScope
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import (
    ComputeScope,
    normalize_export_scope_to_compute_scope,
)


@dataclass(frozen=True)
class PlannedComputeNode:
    """One DAG vertex discovered by export dependency walk."""

    scope: ComputeScope
    export_scope: ExportScope
    dependency_scopes: tuple[ComputeScope, ...]


def _pending_key(analytic_id: str, export_scope: ExportScope) -> tuple[str, ExportScope]:
    return (analytic_id, export_scope)


def plan_compute_dag(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    export_scope: ExportScope,
    *,
    compute_registry: Mapping[str, AnalyticComputeRegistration],
    force_root: bool = False,
) -> tuple[PlannedComputeNode, ...]:
    """Plan compute nodes and dependency edges from ENSURE_DEPENDENCIES walk."""
    walk_result = walk_dependency_tree(
        ctx,
        analytic_id,
        export_scope,
        visiting=set(),
        force_root=force_root,
    )
    if walk_result.turn_unavailable is not None:
        raise ValueError(
            f"cannot plan compute DAG: turn unavailable ({walk_result.turn_unavailable})"
        )

    pending_by_key: dict[tuple[str, ExportScope], tuple[str, ExportScope, object]] = {}
    for pending_analytic_id, pending_scope, catalog in walk_result.pending_ensure:
        pending_by_key[_pending_key(pending_analytic_id, pending_scope)] = (
            pending_analytic_id,
            pending_scope,
            catalog,
        )

    planned: list[PlannedComputeNode] = []
    for pending_analytic_id, pending_scope, catalog in walk_result.pending_ensure:
        compute_registration = compute_registry.get(pending_analytic_id)
        if compute_registration is None:
            raise RuntimeError(
                f"compute registry missing analytic {pending_analytic_id!r} required by DAG plan"
            )
        scope = normalize_export_scope_to_compute_scope(
            pending_scope,
            analytic_id=pending_analytic_id,
            scope_key_spec=compute_registration.scope_key_spec,
        )
        dependency_scopes: list[ComputeScope] = []
        for dependency in catalog.ensure_dependencies:
            dependency_export_scope = dependency_scope_for(pending_scope, dependency)
            turn_floor = ensure_dependency_turn_floor(
                ctx,
                pending_scope,
                analytic_id=pending_analytic_id,
                dependency_analytic_id=dependency.analytic_id,
            )
            if dependency_export_scope.turn < turn_floor:
                continue
            dependency_key = _pending_key(dependency.analytic_id, dependency_export_scope)
            if dependency_key not in pending_by_key:
                continue
            dependency_registration = compute_registry[dependency.analytic_id]
            dependency_scopes.append(
                normalize_export_scope_to_compute_scope(
                    dependency_export_scope,
                    analytic_id=dependency.analytic_id,
                    scope_key_spec=dependency_registration.scope_key_spec,
                )
            )
        planned.append(
            PlannedComputeNode(
                scope=scope,
                export_scope=pending_scope,
                dependency_scopes=tuple(dependency_scopes),
            )
        )
    return tuple(planned)
