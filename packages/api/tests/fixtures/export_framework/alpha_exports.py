"""Test-only export catalog for export-test-alpha."""

from __future__ import annotations

from typing import Any

from api.analytics.export_types import EnsureDependency, ExportScope
from tests.fixtures.export_framework.fixture_catalog import (
    ALPHA_EXPORT_VALUE_SCHEMA,
    make_fixture_catalog,
)
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE

ANALYTIC_ID = "export-test-alpha"


def _materialize_alpha(ctx: object, scope: ExportScope) -> dict[str, Any]:
    FIXTURE_EXPORT_STATE.materialize_calls.append((ANALYTIC_ID, scope))
    if FIXTURE_EXPORT_STATE.cycle_on_materialize:
        from api.analytics.export_context import AnalyticQueryContext

        assert isinstance(ctx, AnalyticQueryContext)
        ctx.query(
            ANALYTIC_ID,
            ["$.payload.label"],
            {"turn": scope.turn, "player_id": scope.player_id},
        )
    return {
        "payload": {
            "label": f"alpha-t{scope.turn}-p{scope.player_id}",
            "items": [],
        },
        "meta": {"searchStatus": "complete"},
    }


EXPORT_CATALOG = make_fixture_catalog(
    ANALYTIC_ID,
    value_schema=ALPHA_EXPORT_VALUE_SCHEMA,
    ensure_dependencies=(
        EnsureDependency(analytic_id="export-test-beta", turn_delta=-1, player_id="same"),
    ),
    materialize_export_tree=_materialize_alpha,
)
