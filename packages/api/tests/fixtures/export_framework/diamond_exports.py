"""Test-only export catalogs with a diamond ensure dependency graph."""

from __future__ import annotations

from api.analytics.export_types import EnsureDependency
from tests.fixtures.export_framework.fixture_catalog import make_fixture_catalog

ROOT_ID = "export-test-diamond-root"
BRANCH_B_ID = "export-test-diamond-b"
BRANCH_C_ID = "export-test-diamond-c"
SHARED_ID = "export-test-diamond-shared"

SHARED_EXPORT_CATALOG = make_fixture_catalog(SHARED_ID)

BRANCH_B_EXPORT_CATALOG = make_fixture_catalog(
    BRANCH_B_ID,
    ensure_dependencies=(EnsureDependency(analytic_id=SHARED_ID, turn_delta=0, player_id="same"),),
)

BRANCH_C_EXPORT_CATALOG = make_fixture_catalog(
    BRANCH_C_ID,
    ensure_dependencies=(EnsureDependency(analytic_id=SHARED_ID, turn_delta=0, player_id="same"),),
)

ROOT_EXPORT_CATALOG = make_fixture_catalog(
    ROOT_ID,
    ensure_dependencies=(
        EnsureDependency(analytic_id=BRANCH_B_ID, turn_delta=0, player_id="same"),
        EnsureDependency(analytic_id=BRANCH_C_ID, turn_delta=0, player_id="same"),
    ),
)
