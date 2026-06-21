"""In-process analytic export query context."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
    ExportScopeOverridesMapping,
    PathResult,
    ResolutionKey,
    UnavailableReason,
)
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.jsonpath import parse_jsonpath, resolve_jsonpath
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.services.inference_row_persistence_service import InferenceRowPersistenceService

INLINE_ENSURE_MAX_MISSING_STEPS = 5


@dataclass(frozen=True)
class ScoresExportContext:
    """Inference services used by scores export ensure and materialization."""

    persistence: InferenceRowPersistenceService | None = None
    scheduler: InferenceRowScheduler | None = None
    resolve_hull_catalog_mask: Callable[[TurnInfo, int], ResolvedHullCatalogMask | None] | None = (
        None
    )


@dataclass(frozen=True)
class PreparedExportRequest:
    """Catalog and scope resolved for one probe or query."""

    catalog: AnalyticExportCatalog
    scope: ExportScope


@dataclass(frozen=True)
class PlannedEnsureWalk:
    """Prepared request plus dependency walk outcome for probe or query."""

    prep: PreparedExportRequest
    walk_result: DependencyWalkResult
    blocked_inline: bool


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
    scores_export: ScoresExportContext | None = None
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

    def is_scope_ensured(self, analytic_id: str, scope: ExportScope) -> bool:
        return (analytic_id, scope) in self._ensured_scopes

    def mark_scope_ensured(self, analytic_id: str, scope: ExportScope) -> None:
        self._ensured_scopes.add((analytic_id, scope))

    def probe(
        self,
        analytic_id: str,
        scope_overrides: ExportScopeOverrides | ExportScopeOverridesMapping | None = None,
    ) -> ExportProbeResult:
        """Dry-run ensure dependencies without materialization."""
        plan = self._plan_ensure_walk(
            analytic_id,
            scope_overrides,
            pre_walk_unavailable=lambda prep: self._requested_turn_unavailable_reason(prep.scope),
            catch_ensure_cycle=True,
        )
        if not isinstance(plan, PlannedEnsureWalk):
            return self._probe_unavailable(plan)
        walk_result = plan.walk_result
        total_missing = len(walk_result.missing_steps)
        return ExportProbeResult(
            status="ok",
            missing_steps=tuple(walk_result.missing_steps),
            total_missing=total_missing,
            blocked_inline=plan.blocked_inline,
        )

    def query(
        self,
        analytic_id: str,
        paths: list[str] | tuple[str, ...],
        scope_overrides: ExportScopeOverrides | ExportScopeOverridesMapping | None = None,
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
            cached = self._memo[resolution_key]
            if not (
                force_inline_ensure
                and cached.status == "unavailable"
                and cached.reason == "ensure_blocked"
            ):
                return cached
        if resolution_key in self._resolution_stack:
            raise ExportCycleDetectedError(
                f"Analytic export cycle detected for {analytic_id!r} "
                f"at turn {scope.turn} with paths {list(normalized_paths)!r}"
            )

        plan = self._plan_ensure_walk(
            analytic_id,
            scope_overrides,
            prep=prep,
            pre_walk_unavailable=lambda prepared: self._scope_unavailable_reason(
                prepared.catalog,
                prepared.scope,
                normalized_paths,
            ),
            catch_ensure_cycle=False,
        )
        if not isinstance(plan, PlannedEnsureWalk):
            result = self._unavailable(plan)
            self._memo[resolution_key] = result
            return result

        if plan.blocked_inline and not force_inline_ensure and self.enforce_inline_ensure_threshold:
            return self._unavailable("ensure_blocked")

        walk_result = plan.walk_result
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

    def _plan_ensure_walk(
        self,
        analytic_id: str,
        scope_overrides: ExportScopeOverrides | ExportScopeOverridesMapping | None,
        *,
        prep: PreparedExportRequest | None = None,
        pre_walk_unavailable: Callable[[PreparedExportRequest], UnavailableReason | None],
        catch_ensure_cycle: bool,
    ) -> UnavailableReason | PlannedEnsureWalk:
        resolved_prep = prep
        if resolved_prep is None:
            prepared = self._prepare_export_request(analytic_id, scope_overrides)
            if not isinstance(prepared, PreparedExportRequest):
                return prepared
            resolved_prep = prepared
        unavailable = pre_walk_unavailable(resolved_prep)
        if unavailable is not None:
            return unavailable
        walk_outcome = self._walk_export_dependencies(
            analytic_id,
            resolved_prep.scope,
            catch_ensure_cycle=catch_ensure_cycle,
        )
        if not isinstance(walk_outcome, DependencyWalkResult):
            return walk_outcome
        total_missing = len(walk_outcome.missing_steps)
        return PlannedEnsureWalk(
            prep=resolved_prep,
            walk_result=walk_outcome,
            blocked_inline=total_missing > INLINE_ENSURE_MAX_MISSING_STEPS,
        )

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
        scope_overrides: ExportScopeOverrides | ExportScopeOverridesMapping | None,
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
        scope_overrides: ExportScopeOverrides | ExportScopeOverridesMapping | None,
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
        scope_overrides: ExportScopeOverrides | ExportScopeOverridesMapping | None,
    ) -> ExportScopeOverrides:
        if scope_overrides is None:
            return ExportScopeOverrides()
        if isinstance(scope_overrides, ExportScopeOverrides):
            return scope_overrides
        return ExportScopeOverrides(
            turn=scope_overrides.get("turn"),
            player_id=scope_overrides.get("player_id"),
        )

    def _requested_turn_unavailable_reason(
        self,
        scope: ExportScope,
    ) -> UnavailableReason | None:
        if self.load_turn(scope.turn) is None:
            return "turn_not_stored"
        return None

    def _scope_unavailable_reason(
        self,
        catalog: AnalyticExportCatalog,
        scope: ExportScope,
        paths: tuple[str, ...],
    ) -> UnavailableReason | None:
        unavailable = self._requested_turn_unavailable_reason(scope)
        if unavailable is not None:
            return unavailable
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
            self.mark_scope_ensured(analytic_id, scope)

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
    scores_export: ScoresExportContext | None = None,
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
        scores_export=scores_export,
    )
