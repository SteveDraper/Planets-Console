"""Test-only export catalog whose scope at turn ``t`` ensures itself at turn ``t - 1``."""

from __future__ import annotations

from api.analytics.export_types import EnsureDependency
from tests.fixtures.export_framework.fixture_catalog import make_fixture_catalog

CHAIN_ID = "export-test-turn-chain"

CHAIN_EXPORT_CATALOG = make_fixture_catalog(
    CHAIN_ID,
    ensure_dependencies=(EnsureDependency(analytic_id=CHAIN_ID, turn_delta=-1, player_id="same"),),
)
