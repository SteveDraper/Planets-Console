"""Test-only export catalog for export-test-beta."""

from __future__ import annotations

from typing import Any

from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE

ANALYTIC_ID = "export-test-beta"

ENSURE_DEPENDENCIES = (
    EnsureDependency(analytic_id="export-test-alpha", turn_delta=0, player_id="same"),
)

EXPORT_VALUE_SCHEMA = {
    "type": "object",
    "properties": {
        "payload": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "items": {"type": "array"},
            },
        },
    },
}

PATH_PREFIX_SCOPE_RULES = (PathPrefixScopeRule(prefix="$.payload", requires=("player_id",)),)


def is_persisted(_ctx: object, scope: ExportScope) -> bool:
    return FIXTURE_EXPORT_STATE.is_persisted(ANALYTIC_ID, scope)


def ensure_export(_ctx: object, scope: ExportScope) -> None:
    FIXTURE_EXPORT_STATE.ensure_calls.append((ANALYTIC_ID, scope))
    FIXTURE_EXPORT_STATE.mark_persisted(ANALYTIC_ID, scope)


def materialize_export_tree(_ctx: object, scope: ExportScope) -> dict[str, Any]:
    FIXTURE_EXPORT_STATE.materialize_calls.append((ANALYTIC_ID, scope))
    return {
        "payload": {
            "label": f"beta-t{scope.turn}-p{scope.player_id}",
            "items": [{"id": 1}],
        },
    }


EXPORT_CATALOG = AnalyticExportCatalog(
    analytic_id=ANALYTIC_ID,
    value_schema=EXPORT_VALUE_SCHEMA,
    path_prefix_scope_rules=PATH_PREFIX_SCOPE_RULES,
    ensure_dependencies=ENSURE_DEPENDENCIES,
    ensure_export=ensure_export,
    materialize_export_tree=materialize_export_tree,
    is_persisted=is_persisted,
)
