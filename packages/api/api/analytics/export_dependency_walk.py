"""Single-pass dependency tree walk for analytic export ensure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from api.analytics.export_errors import ExportCycleDetectedError
from api.analytics.export_types import (
    EnsureDependency,
    EnsureDependencyQuality,
    EnsureMissingStep,
    ExportScope,
    UnavailableReason,
)
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.ensure_validation import validate_ensure_dependency_target
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import GameSettings

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext

T = TypeVar("T")
K = TypeVar("K")


def _settings_for_ensure_scope(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> GameSettings | None:
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        turn = ctx.load_turn(ctx.ambient_turn)
    return turn.settings if turn is not None else None


def ensure_dependency_turn_floor(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> int:
    """Return the ensure floor for dependency edges (1, or accelerated N).

    Floor is a game-domain rule from settings + requesting scope turn -- not
    gated by analytic id.
    """
    settings = _settings_for_ensure_scope(ctx, scope)
    if settings is None:
        return 1
    return accelerated_ensure_floor(settings, scope.turn)


@dataclass
class DependencyWalkResult:
    turn_unavailable: UnavailableReason | None = None
    """When ``turn_unavailable`` is ``turn_not_stored``, the missing turn number if known."""
    unavailable_turn: int | None = None
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
    force_root: bool = False,
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
        if catalog is None or catalog.is_empty:
            return result
        if not force_root and not _dependency_needs_processing(ctx, analytic_id, scope, catalog):
            return result

        for dependency in catalog.ensure_dependencies:
            for dependency_scope in dependency_scopes_for(ctx, scope, dependency):
                turn_floor = ensure_dependency_turn_floor(ctx, scope)
                if dependency_scope.turn < turn_floor:
                    continue

                if ctx.load_turn(dependency_scope.turn) is None:
                    result.turn_unavailable = "turn_not_stored"
                    result.unavailable_turn = dependency_scope.turn
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
                    result.unavailable_turn = nested.unavailable_turn
                    return result

                _extend_unique(
                    result.missing_steps,
                    nested.missing_steps,
                    seen_missing,
                    _missing_step_key,
                )
                _extend_unique(
                    result.pending_ensure,
                    nested.pending_ensure,
                    seen_pending,
                    _pending_ensure_key,
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


def _extend_unique(
    target: list[T],
    source: list[T],
    seen: set[K],
    key_fn: Callable[[T], K],
) -> None:
    for item in source:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        target.append(item)


def _missing_step_key(step: EnsureMissingStep) -> tuple[str, int, int | None]:
    return (step.analytic_id, step.turn, step.player_id)


def _pending_ensure_key(
    item: tuple[str, ExportScope, AnalyticExportCatalog],
) -> tuple[str, ExportScope]:
    analytic_id, scope, _catalog = item
    return (analytic_id, scope)


def dependency_scope_for(
    scope: ExportScope,
    dependency: EnsureDependency,
) -> ExportScope:
    """Map one ensure edge to one child scope (``same`` / ``None`` only).

    For ``player_id="all"`` use :func:`dependency_scopes_for` instead.
    """
    if dependency.player_id == "all":
        raise ValueError(
            "EnsureDependency.player_id='all' expands to multiple scopes; use dependency_scopes_for"
        )
    player_id = scope.player_id
    if dependency.player_id != "same":
        player_id = None
    return ExportScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn + dependency.turn_delta,
        player_id=player_id,
    )


def dependency_scopes_for(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    dependency: EnsureDependency,
) -> tuple[ExportScope, ...]:
    """Expand one ensure edge to one or more child scopes.

    ``player_id="all"`` fans out to every roster player at the dependency turn.
    When that turn is not stored, returns a single unscoped placeholder so the
    walk can report ``turn_not_stored`` (same as a missing same-player dep turn).
    """
    if dependency.player_id != "all":
        return (dependency_scope_for(scope, dependency),)

    dep_turn = scope.turn + dependency.turn_delta
    turn = ctx.load_turn(dep_turn)
    if turn is None:
        return (
            ExportScope(
                game_id=scope.game_id,
                perspective=scope.perspective,
                turn=dep_turn,
                player_id=None,
            ),
        )
    from api.analytics.turn_roster import iter_turn_players

    return tuple(
        ExportScope(
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn=dep_turn,
            player_id=player.id,
        )
        for player in iter_turn_players(turn)
    )


def _dependency_needs_processing(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    catalog: AnalyticExportCatalog | None,
) -> bool:
    """Whether ``scope`` still needs ensure work (and thus belongs in a DAG plan).

    Prior-turn edges that fall below the ensure floor are skipped when walking
    dependencies; they must not elide an unsatisfied root. Homeworld (and fleet)
    at turn 1 still need baseline/materialize even when ``turn_delta=-1`` points
    at turn 0.
    """
    if catalog is None or catalog.is_empty:
        return False
    if is_export_scope_ensure_satisfied(ctx, analytic_id, scope, catalog):
        return False
    return True


def is_ensure_dependency_satisfied(
    ctx: AnalyticQueryContext,
    dependency: EnsureDependency,
    scope: ExportScope,
) -> bool:
    """Cheap probe: whether one declared ensure edge is already satisfied."""
    catalog = ctx.export_registry.get(dependency.analytic_id)
    if catalog is None or catalog.is_empty:
        return True
    return all(
        is_export_scope_ensure_satisfied(
            ctx,
            dependency.analytic_id,
            dependency_scope,
            catalog,
            quality=dependency.quality,
        )
        for dependency_scope in dependency_scopes_for(ctx, scope, dependency)
    )


def is_export_scope_ensure_satisfied(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    scope: ExportScope,
    catalog: AnalyticExportCatalog,
    *,
    quality: EnsureDependencyQuality = "final",
) -> bool:
    """Cheap probe/ensure gate: must not run inference or materialize export payloads."""
    if ctx.is_scope_ensured(analytic_id, scope):
        return True
    if quality == "observation" and analytic_id == "fleet":
        from api.analytics.fleet.exports import is_fleet_export_observation_satisfied

        return is_fleet_export_observation_satisfied(ctx, scope)
    if catalog.is_ensure_satisfied is not None:
        return catalog.is_ensure_satisfied(ctx, scope)
    if catalog.is_persisted is None:
        return False
    return catalog.is_persisted(ctx, scope)
