"""In-process analytic export query context."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from api.analytics.export_errors import ExportCycleDetectedError
from api.analytics.export_types import (
    EnsureDependency,
    EnsureMissingStep,
    ExportProbeResult,
    ExportQueryResult,
    ExportScope,
    ExportScopeOverrides,
    PathResult,
    ResolutionKey,
    UnavailableReason,
)
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.jsonpath import parse_jsonpath, resolve_jsonpath
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import TurnInfo

INLINE_ENSURE_MAX_MISSING_STEPS = 5

_CONTINUE = object()


class _ExportDependencyVisitor(Protocol):
    def on_cycle(self, analytic_id: str, scope: ExportScope) -> Any: ...

    def on_node_enter(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog | None,
    ) -> Any: ...

    def on_dependency_missing_turn(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
    ) -> Any: ...

    def should_visit_dependency(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
        dependency_catalog: AnalyticExportCatalog | None,
    ) -> bool: ...

    def on_dependency_result(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
        nested: Any,
    ) -> Any: ...

    def on_node_exit(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog,
    ) -> Any: ...


@dataclass
class _TurnAvailabilityVisitor:
    def on_cycle(self, analytic_id: str, scope: ExportScope) -> UnavailableReason | None:
        return None

    def on_node_enter(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog | None,
    ) -> Any:
        return _CONTINUE

    def on_dependency_missing_turn(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
    ) -> Any:
        return "turn_not_stored"

    def should_visit_dependency(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
        dependency_catalog: AnalyticExportCatalog | None,
    ) -> bool:
        return dependency_catalog is not None and not dependency_catalog.is_empty

    def on_dependency_result(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
        nested: UnavailableReason | None,
    ) -> Any:
        if nested is not None:
            return nested
        return _CONTINUE

    def on_node_exit(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog,
    ) -> UnavailableReason | None:
        return None


@dataclass
class _MissingStepsVisitor:
    ctx: AnalyticQueryContext
    missing: list[EnsureMissingStep] = field(default_factory=list)

    def on_cycle(self, analytic_id: str, scope: ExportScope) -> list[EnsureMissingStep]:
        return []

    def on_node_enter(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog | None,
    ) -> Any:
        if catalog is None or catalog.is_empty:
            return []
        if self.ctx._is_at_baseline(analytic_id, scope, catalog):
            return []
        if self.ctx._is_persisted(analytic_id, scope, catalog):
            return []
        return _CONTINUE

    def on_dependency_missing_turn(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
    ) -> Any:
        self.missing.append(
            EnsureMissingStep(
                analytic_id=dependency.analytic_id,
                turn=dependency_scope.turn,
                player_id=dependency_scope.player_id,
                status="not_persisted",
            )
        )
        return _CONTINUE

    def should_visit_dependency(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
        dependency_catalog: AnalyticExportCatalog | None,
    ) -> bool:
        return True

    def on_dependency_result(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
        nested: list[EnsureMissingStep],
    ) -> Any:
        return _CONTINUE

    def on_node_exit(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog,
    ) -> list[EnsureMissingStep]:
        self.missing.append(
            EnsureMissingStep(
                analytic_id=analytic_id,
                turn=scope.turn,
                player_id=scope.player_id,
                status="not_persisted",
            )
        )
        return self.missing


@dataclass
class _EnsureExportVisitor:
    ctx: AnalyticQueryContext

    def on_cycle(self, analytic_id: str, scope: ExportScope) -> None:
        raise ExportCycleDetectedError(
            f"Analytic export ensure cycle detected for {analytic_id!r} "
            f"at turn {scope.turn} with player_id {scope.player_id!r}"
        )

    def on_node_enter(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog | None,
    ) -> Any:
        if catalog is None or catalog.is_empty:
            return None
        if self.ctx._is_at_baseline(analytic_id, scope, catalog):
            return None
        if self.ctx._is_persisted(analytic_id, scope, catalog):
            return None
        return _CONTINUE

    def on_dependency_missing_turn(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
    ) -> Any:
        return _CONTINUE

    def should_visit_dependency(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
        dependency_catalog: AnalyticExportCatalog | None,
    ) -> bool:
        return True

    def on_dependency_result(
        self,
        dependency: EnsureDependency,
        dependency_scope: ExportScope,
        nested: None,
    ) -> Any:
        return _CONTINUE

    def on_node_exit(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog,
    ) -> None:
        if catalog.ensure_export is not None:
            catalog.ensure_export(self.ctx, scope)
        self.ctx._ensured_scopes.add((analytic_id, scope))


@dataclass
class AnalyticQueryContext:
    """Cross-analytic export queries during Core turn analytic compute."""

    game_id: int
    perspective: int
    ambient_turn: int
    options: TurnAnalyticsOptions
    load_turn: Callable[[int], TurnInfo | None]
    export_registry: Mapping[str, AnalyticExportCatalog]
    allow_inline_ensure: bool = True
    _memo: dict[ResolutionKey, ExportQueryResult] = field(default_factory=dict, repr=False)
    _materialized_trees: dict[tuple[str, ExportScope], dict[str, Any]] = field(
        default_factory=dict,
        repr=False,
    )
    _resolution_stack: list[ResolutionKey] = field(default_factory=list, repr=False)
    _ensured_scopes: set[tuple[str, ExportScope]] = field(default_factory=set, repr=False)

    def probe(
        self,
        analytic_id: str,
        scope_overrides: ExportScopeOverrides | Mapping[str, object] | None = None,
    ) -> ExportProbeResult:
        """Dry-run ensure dependencies without materialization."""
        catalog = self._catalog_or_none(analytic_id)
        if catalog is None:
            return self._probe_unavailable("unknown_analytic")
        if catalog.is_empty:
            return self._probe_unavailable("empty_catalog")
        scope = self._resolve_scope(scope_overrides)
        missing = self._collect_missing_steps(analytic_id, scope, visiting=set())
        total_missing = len(missing)
        blocked_inline = total_missing > INLINE_ENSURE_MAX_MISSING_STEPS
        return ExportProbeResult(
            status="ok",
            missing_steps=tuple(missing),
            total_missing=total_missing,
            blocked_inline=blocked_inline,
        )

    def query(
        self,
        analytic_id: str,
        paths: list[str] | tuple[str, ...],
        scope_overrides: ExportScopeOverrides | Mapping[str, object] | None = None,
        *,
        force_inline_ensure: bool = False,
    ) -> ExportQueryResult:
        """Ensure, materialize, and resolve JSONPath selectors for one analytic."""
        normalized_paths = tuple(sorted(paths))
        scope = self._resolve_scope(scope_overrides)
        resolution_key = ResolutionKey(
            analytic_id=analytic_id,
            scope=scope,
            paths=normalized_paths,
        )
        if resolution_key in self._memo:
            return self._memo[resolution_key]
        if resolution_key in self._resolution_stack:
            raise ExportCycleDetectedError(
                f"Analytic export cycle detected for {analytic_id!r} "
                f"at turn {scope.turn} with paths {list(normalized_paths)!r}"
            )

        catalog = self._catalog_or_none(analytic_id)
        if catalog is None:
            return self._unavailable("unknown_analytic")
        if catalog.is_empty:
            return self._unavailable("empty_catalog")

        unavailable = self._scope_unavailable_reason(catalog, scope, normalized_paths)
        if unavailable is not None:
            result = self._unavailable(unavailable)
            self._memo[resolution_key] = result
            return result

        dependency_unavailable = self._dependency_turn_unavailable(analytic_id, scope)
        if dependency_unavailable is not None:
            result = self._unavailable(dependency_unavailable)
            self._memo[resolution_key] = result
            return result

        probe_result = self.probe(analytic_id, scope_overrides)
        if probe_result.status == "unavailable":
            result = self._unavailable(probe_result.reason)  # type: ignore[arg-type]
            self._memo[resolution_key] = result
            return result
        if probe_result.blocked_inline and not force_inline_ensure and self.allow_inline_ensure:
            result = self._unavailable("ensure_blocked")
            self._memo[resolution_key] = result
            return result

        self._resolution_stack.append(resolution_key)
        try:
            self._ensure_export_tree(analytic_id, scope)
            tree = self._materialize_tree(analytic_id, scope, catalog)
            path_results = {
                path: self._resolve_path_result(catalog, scope, tree, path) for path in paths
            }
            result = ExportQueryResult(status="ok", paths=path_results)
            self._memo[resolution_key] = result
            return result
        finally:
            self._resolution_stack.pop()

    def _catalog_or_none(self, analytic_id: str) -> AnalyticExportCatalog | None:
        return self.export_registry.get(analytic_id)

    def _resolve_scope(
        self,
        scope_overrides: ExportScopeOverrides | Mapping[str, object] | None,
    ) -> ExportScope:
        overrides = self._coerce_overrides(scope_overrides)
        return ExportScope(
            game_id=self.game_id,
            perspective=self.perspective,
            turn=overrides.turn if overrides.turn is not None else self.ambient_turn,
            player_id=overrides.player_id,
        )

    @staticmethod
    def _coerce_overrides(
        scope_overrides: ExportScopeOverrides | Mapping[str, object] | None,
    ) -> ExportScopeOverrides:
        if scope_overrides is None:
            return ExportScopeOverrides()
        if isinstance(scope_overrides, ExportScopeOverrides):
            return scope_overrides
        return ExportScopeOverrides(
            turn=scope_overrides.get("turn"),  # type: ignore[arg-type]
            player_id=scope_overrides.get("player_id"),  # type: ignore[arg-type]
        )

    def _scope_unavailable_reason(
        self,
        catalog: AnalyticExportCatalog,
        scope: ExportScope,
        paths: tuple[str, ...],
    ) -> UnavailableReason | None:
        if self.load_turn(scope.turn) is None:
            return "turn_not_stored"
        for path in paths:
            if catalog.requires_player_id_for_path(path) and scope.player_id is None:
                return "invalid_scope"
        return None

    def _dependency_turn_unavailable(
        self,
        analytic_id: str,
        scope: ExportScope,
    ) -> UnavailableReason | None:
        catalog = self.export_registry.get(analytic_id)
        if catalog is None or catalog.is_empty:
            return None
        return self._walk_dependency_turns(catalog, scope, visiting=set())

    def _walk_export_dependencies(
        self,
        analytic_id: str,
        scope: ExportScope,
        *,
        visiting: set[tuple[str, ExportScope]] | None,
        visitor: _ExportDependencyVisitor,
        catalog_override: AnalyticExportCatalog | None = None,
    ) -> Any:
        visit_key = (analytic_id, scope)
        if visiting is not None:
            if visit_key in visiting:
                return visitor.on_cycle(analytic_id, scope)
            visiting.add(visit_key)

        try:
            catalog = (
                catalog_override
                if catalog_override is not None
                else self.export_registry.get(analytic_id)
            )

            enter_result = visitor.on_node_enter(analytic_id, scope, catalog)
            if enter_result is not _CONTINUE:
                return enter_result

            assert catalog is not None

            for dependency in catalog.ensure_dependencies:
                dependency_scope = self._dependency_scope(scope, dependency)
                if dependency_scope.turn < 1:
                    continue

                if self.load_turn(dependency_scope.turn) is None:
                    missing_turn_result = visitor.on_dependency_missing_turn(
                        dependency,
                        dependency_scope,
                    )
                    if missing_turn_result is not _CONTINUE:
                        return missing_turn_result
                    continue

                dependency_catalog = self.export_registry.get(dependency.analytic_id)
                if not visitor.should_visit_dependency(
                    dependency,
                    dependency_scope,
                    dependency_catalog,
                ):
                    continue

                nested = self._walk_export_dependencies(
                    dependency.analytic_id,
                    dependency_scope,
                    visiting=visiting,
                    visitor=visitor,
                )
                dependency_result = visitor.on_dependency_result(
                    dependency,
                    dependency_scope,
                    nested,
                )
                if dependency_result is not _CONTINUE:
                    return dependency_result

            return visitor.on_node_exit(analytic_id, scope, catalog)
        finally:
            if visiting is not None:
                visiting.discard(visit_key)

    def _walk_dependency_turns(
        self,
        catalog: AnalyticExportCatalog,
        scope: ExportScope,
        *,
        visiting: set[tuple[str, ExportScope]],
    ) -> UnavailableReason | None:
        return self._walk_export_dependencies(
            catalog.analytic_id,
            scope,
            visiting=visiting,
            visitor=_TurnAvailabilityVisitor(),
            catalog_override=catalog,
        )

    def _collect_missing_steps(
        self,
        analytic_id: str,
        scope: ExportScope,
        *,
        visiting: set[tuple[str, ExportScope]],
    ) -> list[EnsureMissingStep]:
        visitor = _MissingStepsVisitor(ctx=self)
        return self._walk_export_dependencies(
            analytic_id,
            scope,
            visiting=visiting,
            visitor=visitor,
        )

    def _dependency_scope(
        self,
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

    def _is_at_baseline(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog,
    ) -> bool:
        if scope.turn <= 1 and not catalog.ensure_dependencies:
            return True
        if scope.turn <= 1:
            for dependency in catalog.ensure_dependencies:
                dependency_scope = self._dependency_scope(scope, dependency)
                if dependency_scope.turn < 1:
                    return True
        return False

    def _is_persisted(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog,
    ) -> bool:
        scope_key = (analytic_id, scope)
        if scope_key in self._ensured_scopes:
            return True
        if catalog.is_persisted is None:
            return False
        return catalog.is_persisted(self, scope)

    def _ensure_export_tree(self, analytic_id: str, scope: ExportScope) -> None:
        catalog = self.export_registry[analytic_id]
        self._walk_export_dependencies(
            analytic_id,
            scope,
            visiting=set(),
            visitor=_EnsureExportVisitor(ctx=self),
            catalog_override=catalog,
        )

    def _materialize_tree(
        self,
        analytic_id: str,
        scope: ExportScope,
        catalog: AnalyticExportCatalog,
    ) -> dict[str, Any]:
        cache_key = (analytic_id, scope)
        if cache_key in self._materialized_trees:
            return self._materialized_trees[cache_key]
        if catalog.materialize_export_tree is None:
            tree: dict[str, Any] = {}
        else:
            tree = catalog.materialize_export_tree(self, scope)
        self._materialized_trees[cache_key] = tree
        return tree

    def _resolve_path_result(
        self,
        catalog: AnalyticExportCatalog,
        scope: ExportScope,
        tree: dict[str, Any],
        path: str,
    ) -> PathResult:
        if catalog.requires_player_id_for_path(path) and scope.player_id is None:
            return PathResult(kind="invalid_path")
        try:
            parse_jsonpath(path)
        except ValueError:
            return PathResult(kind="invalid_path")
        matches = resolve_jsonpath(tree, path)
        if not matches:
            return PathResult(kind="none")
        if len(matches) == 1:
            return PathResult(kind="value", value=matches[0])
        return PathResult(kind="value", value=matches)

    @staticmethod
    def _unavailable(reason: UnavailableReason) -> ExportQueryResult:
        return ExportQueryResult(status="unavailable", reason=reason)

    @staticmethod
    def _probe_unavailable(reason: UnavailableReason) -> ExportProbeResult:
        return ExportProbeResult(status="unavailable", reason=reason)


def make_analytic_query_context(
    turn: TurnInfo,
    options: TurnAnalyticsOptions,
    *,
    load_turn: Callable[[int], TurnInfo | None] | None = None,
    export_registry: Mapping[str, AnalyticExportCatalog] | None = None,
    allow_inline_ensure: bool = True,
) -> AnalyticQueryContext:
    """Build query context with ambient scope from one loaded turn."""
    from api.analytics.exports.registry import EXPORT_REGISTRY

    if load_turn is None:

        def load_turn_for_ambient(stored_turn_number: int) -> TurnInfo | None:
            if stored_turn_number == turn.settings.turn:
                return turn
            return None

        resolved_load_turn = load_turn_for_ambient
    else:
        resolved_load_turn = load_turn

    return AnalyticQueryContext(
        game_id=turn.game.id,
        perspective=turn.player.id,
        ambient_turn=turn.settings.turn,
        options=options,
        load_turn=resolved_load_turn,
        export_registry=export_registry or EXPORT_REGISTRY,
        allow_inline_ensure=allow_inline_ensure,
    )
