"""Test-only export catalog for export-test-beta."""

from __future__ import annotations

from api.analytics.export_types import EnsureDependency
from tests.fixtures.export_framework.fixture_catalog import (
    PAYLOAD_LABEL_ITEMS_SCHEMA,
    make_fixture_catalog,
)

ANALYTIC_ID = "export-test-beta"

EXPORT_CATALOG = make_fixture_catalog(
    ANALYTIC_ID,
    value_schema=PAYLOAD_LABEL_ITEMS_SCHEMA,
    ensure_dependencies=(
        EnsureDependency(analytic_id="export-test-alpha", turn_delta=0, player_id="same"),
    ),
    label_prefix="beta",
    payload_items=[{"id": 1}],
)
