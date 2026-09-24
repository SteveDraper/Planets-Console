"""Per-analytic export catalog bundle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from api.analytics.export_types import (
    EnsureDependency,
    ExportScope,
    PathPrefixScopeRule,
)

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext

EnsureExportFn = Callable[["AnalyticQueryContext", ExportScope], bool]
MaterializeExportFn = Callable[["AnalyticQueryContext", ExportScope], dict[str, Any]]
ProbePersistedFn = Callable[["AnalyticQueryContext", ExportScope], bool]
ProbeEnsureSatisfiedFn = Callable[["AnalyticQueryContext", ExportScope], bool]
ProbeInProgressFn = Callable[["AnalyticQueryContext", ExportScope], bool]
EnsureDependenciesForFn = Callable[
    ["AnalyticQueryContext", ExportScope],
    tuple[EnsureDependency, ...],
]


@dataclass(frozen=True)
class AnalyticExportCatalog:
    """Self-describing export surface for one turn analytic."""

    analytic_id: str
    value_schema: dict[str, Any] | None = None
    path_prefix_scope_rules: tuple[PathPrefixScopeRule, ...] = ()
    ordering_semantics: dict[str, str] = field(default_factory=dict)
    ensure_dependencies: tuple[EnsureDependency, ...] = ()
    ensure_dependencies_for: EnsureDependenciesForFn | None = None
    ensure_export: EnsureExportFn | None = None
    materialize_export_tree: MaterializeExportFn | None = None
    is_persisted: ProbePersistedFn | None = None
    is_ensure_satisfied: ProbeEnsureSatisfiedFn | None = None
    is_in_progress: ProbeInProgressFn | None = None
    is_empty: bool = False

    def applicable_ensure_dependencies(
        self,
        ctx: AnalyticQueryContext,
        scope: ExportScope,
    ) -> tuple[EnsureDependency, ...]:
        """Dependencies the ensure walk and DAG plan enqueue for this scope.

        Static ``ensure_dependencies`` is the default. A catalog may set
        ``ensure_dependencies_for`` when an edge does not apply to every scope
        (fleet skips the prior-turn edge for an eliminated player).
        """
        if self.ensure_dependencies_for is None:
            return self.ensure_dependencies
        return self.ensure_dependencies_for(ctx, scope)

    def requires_player_id_for_path(self, path: str) -> bool:
        for rule in self.path_prefix_scope_rules:
            if (
                path == rule.prefix
                or path.startswith(f"{rule.prefix}.")
                or path.startswith(f"{rule.prefix}[")
            ):
                return "player_id" in rule.requires
        return False
