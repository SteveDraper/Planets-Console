"""Test-only export catalogs with a same-scope ensure dependency cycle."""

from __future__ import annotations

from typing import Any

from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE

CYCLE_A_ID = "export-test-cycle-a"
CYCLE_B_ID = "export-test-cycle-b"

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


CYCLE_A_EXPORT_CATALOG = AnalyticExportCatalog(
    analytic_id=CYCLE_A_ID,
    value_schema=_EXPORT_VALUE_SCHEMA,
    path_prefix_scope_rules=_PATH_PREFIX_SCOPE_RULES,
    ensure_dependencies=(
        EnsureDependency(analytic_id=CYCLE_B_ID, turn_delta=0, player_id="same"),
    ),
    ensure_export=_ensure_export(CYCLE_A_ID),
    materialize_export_tree=_materialize_export_tree(CYCLE_A_ID),
    is_persisted=_is_persisted(CYCLE_A_ID),
)

CYCLE_B_EXPORT_CATALOG = AnalyticExportCatalog(
    analytic_id=CYCLE_B_ID,
    value_schema=_EXPORT_VALUE_SCHEMA,
    path_prefix_scope_rules=_PATH_PREFIX_SCOPE_RULES,
    ensure_dependencies=(
        EnsureDependency(analytic_id=CYCLE_A_ID, turn_delta=0, player_id="same"),
    ),
    ensure_export=_ensure_export(CYCLE_B_ID),
    materialize_export_tree=_materialize_export_tree(CYCLE_B_ID),
    is_persisted=_is_persisted(CYCLE_B_ID),
)
