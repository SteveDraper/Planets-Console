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
from api.analytics.exports.ensure_validation import validate_ensure_dependency_target

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
) -> DependencyWalkResult:
    result = DependencyWalkResult()
    seen_pending: set[tuple[str, ExportScope]] = set()
    seen_missing: set[tuple[str, int, int | None]] = set()
    visit_key = (analytic_id, scope)
    if visit_key in visiting:
        raise ExportCycleDetectedError(
            f"Analytic export ensure cycle detected for {analytic_id!r} "
            f"at turn {scope.turn} with player_id {scope.player_id!r}"
        )

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

            validate_ensure_dependency_target(
                catalog.analytic_id,
                dependency,
                ctx.export_registry,
                role="query",
            )

            nested = walk_dependency_tree(
                ctx,
                dependency.analytic_id,
                dependency_scope,
                visiting=visiting,
            )
            if nested.turn_unavailable is not None:
                result.turn_unavailable = nested.turn_unavailable
                return result

            _extend_unique_missing_steps(
                result.missing_steps,
                nested.missing_steps,
                seen_missing,
            )
            _extend_unique_pending_ensure(
                result.pending_ensure,
                nested.pending_ensure,
                seen_pending,
            )

        result.missing_steps.append(
            EnsureMissingStep(
                analytic_id=analytic_id,
                turn=scope.turn,
                player_id=scope.player_id,
                status="not_persisted",
            ),
        )
        result.pending_ensure.append((analytic_id, scope, catalog))
        return result
    finally:
        visiting.discard(visit_key)


def _missing_step_key(step: EnsureMissingStep) -> tuple[str, int, int | None]:
    return (step.analytic_id, step.turn, step.player_id)


def _extend_unique_missing_steps(
    target: list[EnsureMissingStep],
    source: list[EnsureMissingStep],
    seen: set[tuple[str, int, int | None]],
) -> None:
    for step in source:
        _append_unique_missing_step(target, step, seen)


def _append_unique_missing_step(
    target: list[EnsureMissingStep],
    step: EnsureMissingStep,
    seen: set[tuple[str, int, int | None]],
) -> None:
    key = _missing_step_key(step)
    if key in seen:
        return
    seen.add(key)
    target.append(step)


def _extend_unique_pending_ensure(
    target: list[tuple[str, ExportScope, AnalyticExportCatalog]],
    source: list[tuple[str, ExportScope, AnalyticExportCatalog]],
    seen: set[tuple[str, ExportScope]],
) -> None:
    for item in source:
        _append_unique_pending_ensure(target, item, seen)


def _append_unique_pending_ensure(
    target: list[tuple[str, ExportScope, AnalyticExportCatalog]],
    item: tuple[str, ExportScope, AnalyticExportCatalog],
    seen: set[tuple[str, ExportScope]],
) -> None:
    analytic_id, scope, _catalog = item
    key = (analytic_id, scope)
    if key in seen:
        return
    seen.add(key)
    target.append(item)


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
    if ctx.is_scope_ensured(analytic_id, scope):
        return True
    if catalog.is_persisted is None:
        return False
    return catalog.is_persisted(ctx, scope)
