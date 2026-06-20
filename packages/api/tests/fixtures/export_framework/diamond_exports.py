"""Test-only export catalogs with a diamond ensure dependency graph."""

from __future__ import annotations

from typing import Any

from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE

ROOT_ID = "export-test-diamond-root"
BRANCH_B_ID = "export-test-diamond-b"
BRANCH_C_ID = "export-test-diamond-c"
SHARED_ID = "export-test-diamond-shared"

_PATH_PREFIX_SCOPE_RULES = (PathPrefixScopeRule(prefix="$.payload", requires=("player_id",)),)

_EXPORT_VALUE_SCHEMA = {
    "type": "object",
    "properties": {
        "payload": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
            },
        },
    },
}


def _is_persisted(analytic_id: str):
    def check(_ctx: object, scope: ExportScope) -> bool:
        return FIXTURE_EXPORT_STATE.is_persisted(analytic_id, scope)

    return check


def _ensure_export(analytic_id: str):
    def ensure(_ctx: object, scope: ExportScope) -> None:
        FIXTURE_EXPORT_STATE.ensure_calls.append((analytic_id, scope))
        FIXTURE_EXPORT_STATE.mark_persisted(analytic_id, scope)

    return ensure


def _materialize_export_tree(analytic_id: str):
    def materialize(_ctx: object, scope: ExportScope) -> dict[str, Any]:
        FIXTURE_EXPORT_STATE.materialize_calls.append((analytic_id, scope))
        return {"payload": {"label": f"{analytic_id}-t{scope.turn}-p{scope.player_id}"}}

    return materialize


def _catalog(
    analytic_id: str,
    *,
    ensure_dependencies: tuple[EnsureDependency, ...] = (),
) -> AnalyticExportCatalog:
    return AnalyticExportCatalog(
        analytic_id=analytic_id,
        value_schema=_EXPORT_VALUE_SCHEMA,
        path_prefix_scope_rules=_PATH_PREFIX_SCOPE_RULES,
        ensure_dependencies=ensure_dependencies,
        ensure_export=_ensure_export(analytic_id),
        materialize_export_tree=_materialize_export_tree(analytic_id),
        is_persisted=_is_persisted(analytic_id),
    )


SHARED_EXPORT_CATALOG = _catalog(SHARED_ID)

BRANCH_B_EXPORT_CATALOG = _catalog(
    BRANCH_B_ID,
    ensure_dependencies=(EnsureDependency(analytic_id=SHARED_ID, turn_delta=0, player_id="same"),),
)

BRANCH_C_EXPORT_CATALOG = _catalog(
    BRANCH_C_ID,
    ensure_dependencies=(EnsureDependency(analytic_id=SHARED_ID, turn_delta=0, player_id="same"),),
)

ROOT_EXPORT_CATALOG = _catalog(
    ROOT_ID,
    ensure_dependencies=(
        EnsureDependency(analytic_id=BRANCH_B_ID, turn_delta=0, player_id="same"),
        EnsureDependency(analytic_id=BRANCH_C_ID, turn_delta=0, player_id="same"),
    ),
)
