"""Single-pass dependency tree walk for analytic export ensure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from api.analytics.export_errors import ExportCycleDetectedError
from api.analytics.export_types import (
    EnsureDependency,
    EnsureMissingStep,
    ExportScope,
    UnavailableReason,
)
from api.analytics.exports.catalog import AnalyticExportCatalog

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext


@dataclass
class DependencyWalkResult:
    turn_unavailable: UnavailableReason | None = None
    missing_steps: list[EnsureMissingStep] = field(default_factory=list)
    pending_ensure: list[tuple[str, ExportScope, AnalyticExportCatalog]] = field(
        default_factory=list,
    )


def walk_dependency_tree(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    *,
    visiting: set[tuple[str, ExportScope]],
    detect_ensure_cycles: bool,
) -> DependencyWalkResult:
    result = DependencyWalkResult()
    visit_key = (analytic_id, scope)
    if visit_key in visiting:
        if detect_ensure_cycles:
            raise ExportCycleDetectedError(
                f"Analytic export ensure cycle detected for {analytic_id!r} "
                f"at turn {scope.turn} with player_id {scope.player_id!r}"
            )
        return result

    visiting.add(visit_key)
    try:
        catalog = ctx.export_registry.get(analytic_id)
        if not _dependency_needs_processing(ctx, analytic_id, scope, catalog):
            return result

        assert catalog is not None

        for dependency in catalog.ensure_dependencies:
            dependency_scope = dependency_scope_for(scope, dependency)
            if dependency_scope.turn < 1:
                continue

            if ctx.load_turn(dependency_scope.turn) is None:
                result.turn_unavailable = "turn_not_stored"
                return result

            dependency_catalog = ctx.export_registry.get(dependency.analytic_id)
            if dependency_catalog is None or dependency_catalog.is_empty:
                continue

            nested = walk_dependency_tree(
                ctx,
                dependency.analytic_id,
                dependency_scope,
                visiting=visiting,
                detect_ensure_cycles=detect_ensure_cycles,
            )
            if nested.turn_unavailable is not None:
                result.turn_unavailable = nested.turn_unavailable
                return result

            result.missing_steps.extend(nested.missing_steps)
            result.pending_ensure.extend(nested.pending_ensure)

        result.missing_steps.append(
            EnsureMissingStep(
                analytic_id=analytic_id,
                turn=scope.turn,
                player_id=scope.player_id,
                status="not_persisted",
            )
        )
        result.pending_ensure.append((analytic_id, scope, catalog))
        return result
    finally:
        visiting.discard(visit_key)


def dependency_scope_for(
    scope: ExportScope,
    dependency: EnsureDependency,
) -> ExportScope:
    player_id = scope.player_id
    if dependency.player_id != "same":
        player_id = None
    return ExportScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn + dependency.turn_delta,
        player_id=player_id,
    )


def _dependency_needs_processing(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    catalog: AnalyticExportCatalog | None,
) -> bool:
    if catalog is None or catalog.is_empty:
        return False
    if _is_at_baseline(scope, catalog):
        return False
    if _is_persisted(ctx, analytic_id, scope, catalog):
        return False
    return True


def _is_at_baseline(
    scope: ExportScope,
    catalog: AnalyticExportCatalog,
) -> bool:
    if scope.turn <= 1 and not catalog.ensure_dependencies:
        return True
    if scope.turn <= 1:
        for dependency in catalog.ensure_dependencies:
            dependency_scope = dependency_scope_for(scope, dependency)
            if dependency_scope.turn < 1:
                return True
    return False


def _is_persisted(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    catalog: AnalyticExportCatalog,
) -> bool:
    scope_key = (analytic_id, scope)
    if scope_key in ctx._ensured_scopes:
        return True
    if catalog.is_persisted is None:
        return False
    return catalog.is_persisted(ctx, scope)
