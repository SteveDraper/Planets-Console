"""Test-only export catalogs with a same-scope ensure dependency cycle."""

from __future__ import annotations

from api.analytics.export_types import EnsureDependency
from tests.fixtures.export_framework.fixture_catalog import make_fixture_catalog

CYCLE_A_ID = "export-test-cycle-a"
CYCLE_B_ID = "export-test-cycle-b"

CYCLE_A_EXPORT_CATALOG = make_fixture_catalog(
    CYCLE_A_ID,
    ensure_dependencies=(EnsureDependency(analytic_id=CYCLE_B_ID, turn_delta=0, player_id="same"),),
)

CYCLE_B_EXPORT_CATALOG = make_fixture_catalog(
    CYCLE_B_ID,
    ensure_dependencies=(EnsureDependency(analytic_id=CYCLE_A_ID, turn_delta=0, player_id="same"),),
)
