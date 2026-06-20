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

EnsureExportFn = Callable[["AnalyticQueryContext", ExportScope], None]
MaterializeExportFn = Callable[["AnalyticQueryContext", ExportScope], dict[str, Any]]
ProbePersistedFn = Callable[["AnalyticQueryContext", ExportScope], bool]


@dataclass(frozen=True)
class AnalyticExportCatalog:
    """Self-describing export surface for one turn analytic."""

    analytic_id: str
    value_schema: dict[str, Any] | None = None
    path_prefix_scope_rules: tuple[PathPrefixScopeRule, ...] = ()
    ordering_semantics: dict[str, str] = field(default_factory=dict)
    ensure_dependencies: tuple[EnsureDependency, ...] = ()
    ensure_export: EnsureExportFn | None = None
    materialize_export_tree: MaterializeExportFn | None = None
    is_persisted: ProbePersistedFn | None = None
    is_empty: bool = False

    def requires_player_id_for_path(self, path: str) -> bool:
        for rule in self.path_prefix_scope_rules:
            if (
                path == rule.prefix
                or path.startswith(f"{rule.prefix}.")
                or path.startswith(f"{rule.prefix}[")
            ):
                return "player_id" in rule.requires
        return False
