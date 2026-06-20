"""In-process analytic export query context."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from api.analytics.export_dependency_walk import (
    DependencyWalkResult,
    walk_dependency_tree,
)
from api.analytics.export_errors import ExportCycleDetectedError
from api.analytics.export_types import (
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


@dataclass(frozen=True)
class PreparedExportRequest:
    """Catalog and scope resolved for one probe or query."""

    catalog: AnalyticExportCatalog
    scope: ExportScope


@dataclass
class AnalyticQueryContext:
    """Cross-analytic export queries during Core turn analytic compute."""

    game_id: int
    perspective: int
    ambient_turn: int
    options: TurnAnalyticsOptions
    load_turn: Callable[[int], TurnInfo | None]
    export_registry: Mapping[str, AnalyticExportCatalog]
    enforce_inline_ensure_threshold: bool = True
    # Memo, materialized-tree, and ensure keys use ExportScope (and paths for
    # ResolutionKey) only. TurnAnalyticsOptions connection fields are ambient on
    # ctx.options and are not fingerprinted here (#108 skeleton); connections
    # exports (#110) must extend keying before varying connection options within
    # one request can yield correct cache behaviour.
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
        prep = self._prepare_export_request(analytic_id, scope_overrides)
        if not isinstance(prep, PreparedExportRequest):
            return self._probe_unavailable(prep)
        walk_outcome = self._walk_export_dependencies(
            analytic_id,
            prep.scope,
            catch_ensure_cycle=True,
        )
        if not isinstance(walk_outcome, DependencyWalkResult):
            return self._probe_unavailable(walk_outcome)
        walk_result = walk_outcome
        total_missing = len(walk_result.missing_steps)
        blocked_inline = total_missing > INLINE_ENSURE_MAX_MISSING_STEPS
        return ExportProbeResult(
            status="ok",
            missing_steps=tuple(walk_result.missing_steps),
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
        prep = self._prepare_export_request(analytic_id, scope_overrides)
        if not isinstance(prep, PreparedExportRequest):
            return self._unavailable(prep)

        scope = prep.scope
        catalog = prep.catalog
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

        unavailable = self._scope_unavailable_reason(catalog, scope, normalized_paths)
        if unavailable is not None:
            result = self._unavailable(unavailable)
            self._memo[resolution_key] = result
            return result

        walk_outcome = self._walk_export_dependencies(analytic_id, scope)
        if not isinstance(walk_outcome, DependencyWalkResult):
            result = self._unavailable(walk_outcome)
            self._memo[resolution_key] = result
            return result
        walk_result = walk_outcome

        total_missing = len(walk_result.missing_steps)
        blocked_inline = total_missing > INLINE_ENSURE_MAX_MISSING_STEPS
        if blocked_inline and not force_inline_ensure and self.enforce_inline_ensure_threshold:
            result = self._unavailable("ensure_blocked")
            self._memo[resolution_key] = result
            return result

        self._resolution_stack.append(resolution_key)
        try:
            self._apply_pending_ensure(walk_result.pending_ensure)
            tree = self._materialize_tree(analytic_id, scope, catalog)
            path_results = {
                path: self._resolve_path_result(catalog, scope, tree, path) for path in paths
            }
            result = ExportQueryResult(status="ok", paths=path_results)
            self._memo[resolution_key] = result
            return result
        finally:
            self._resolution_stack.pop()

    def _walk_export_dependencies(
        self,
        analytic_id: str,
        scope: ExportScope,
        *,
        catch_ensure_cycle: bool = False,
    ) -> DependencyWalkResult | UnavailableReason:
        try:
            walk_result = walk_dependency_tree(
                self,
                analytic_id,
                scope,
                visiting=set(),
            )
        except ExportCycleDetectedError:
            if catch_ensure_cycle:
                return "ensure_cycle"
            raise
        if walk_result.turn_unavailable is not None:
            return walk_result.turn_unavailable
        return walk_result

    def _prepare_export_request(
        self,
        analytic_id: str,
        scope_overrides: ExportScopeOverrides | Mapping[str, object] | None,
    ) -> PreparedExportRequest | UnavailableReason:
        catalog = self._catalog_or_none(analytic_id)
        if catalog is None:
            return "unknown_analytic"
        if catalog.is_empty:
            return "empty_catalog"
        scope = self._resolve_scope(scope_overrides)
        return PreparedExportRequest(catalog=catalog, scope=scope)

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

    def _apply_pending_ensure(
        self,
        pending_ensure: list[tuple[str, ExportScope, AnalyticExportCatalog]],
    ) -> None:
        for analytic_id, scope, catalog in pending_ensure:
            if catalog.ensure_export is not None:
                catalog.ensure_export(self, scope)
            self._ensured_scopes.add((analytic_id, scope))

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
    enforce_inline_ensure_threshold: bool = True,
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
        enforce_inline_ensure_threshold=enforce_inline_ensure_threshold,
    )
