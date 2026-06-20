"""Shared factory for export framework fixture catalogs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE

DEFAULT_PATH_PREFIX_SCOPE_RULES = (
    PathPrefixScopeRule(prefix="$.payload", requires=("player_id",)),
)

PAYLOAD_LABEL_SCHEMA = {
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

PAYLOAD_LABEL_ITEMS_SCHEMA = {
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

ALPHA_EXPORT_VALUE_SCHEMA = {
    "type": "object",
    "properties": {
        "payload": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "items": {"type": "array"},
            },
        },
        "meta": {
            "type": "object",
            "properties": {"searchStatus": {"type": "string"}},
        },
    },
}

MaterializeExportTreeFn = Callable[[object, ExportScope], dict[str, Any]]


def _make_is_persisted(analytic_id: str) -> Callable[[object, ExportScope], bool]:
    def is_persisted(_ctx: object, scope: ExportScope) -> bool:
        return FIXTURE_EXPORT_STATE.is_persisted(analytic_id, scope)

    return is_persisted


def _make_ensure_export(analytic_id: str) -> Callable[[object, ExportScope], None]:
    def ensure_export(_ctx: object, scope: ExportScope) -> None:
        FIXTURE_EXPORT_STATE.ensure_calls.append((analytic_id, scope))
        FIXTURE_EXPORT_STATE.mark_persisted(analytic_id, scope)

    return ensure_export


def _make_default_materialize_export_tree(
    analytic_id: str,
    *,
    label_prefix: str | None = None,
    items: list[Any] | None = None,
    root_extra: dict[str, Any] | None = None,
) -> MaterializeExportTreeFn:
    prefix = label_prefix if label_prefix is not None else analytic_id

    def materialize_export_tree(_ctx: object, scope: ExportScope) -> dict[str, Any]:
        FIXTURE_EXPORT_STATE.materialize_calls.append((analytic_id, scope))
        payload: dict[str, Any] = {
            "label": f"{prefix}-t{scope.turn}-p{scope.player_id}",
        }
        if items is not None:
            payload["items"] = items
        tree: dict[str, Any] = {"payload": payload}
        if root_extra:
            tree.update(root_extra)
        return tree

    return materialize_export_tree


def make_fixture_catalog(
    analytic_id: str,
    *,
    value_schema: dict[str, Any] | None = None,
    path_prefix_scope_rules: tuple[PathPrefixScopeRule, ...] | None = None,
    ensure_dependencies: tuple[EnsureDependency, ...] = (),
    materialize_export_tree: MaterializeExportTreeFn | None = None,
    label_prefix: str | None = None,
    payload_items: list[Any] | None = None,
    root_extra: dict[str, Any] | None = None,
) -> AnalyticExportCatalog:
    if materialize_export_tree is None:
        materialize_export_tree = _make_default_materialize_export_tree(
            analytic_id,
            label_prefix=label_prefix,
            items=payload_items,
            root_extra=root_extra,
        )

    return AnalyticExportCatalog(
        analytic_id=analytic_id,
        value_schema=value_schema if value_schema is not None else PAYLOAD_LABEL_SCHEMA,
        path_prefix_scope_rules=(
            path_prefix_scope_rules
            if path_prefix_scope_rules is not None
            else DEFAULT_PATH_PREFIX_SCOPE_RULES
        ),
        ensure_dependencies=ensure_dependencies,
        ensure_export=_make_ensure_export(analytic_id),
        materialize_export_tree=materialize_export_tree,
        is_persisted=_make_is_persisted(analytic_id),
    )
