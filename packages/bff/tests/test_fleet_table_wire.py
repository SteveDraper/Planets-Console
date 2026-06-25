"""Golden vectors: BFF fleet table wire vs test-fixtures/fleet-table-wire.json."""

import json
from pathlib import Path

import pytest

from bff.analytics.fleet import table_from_core

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "test-fixtures" / "fleet-table-wire.json"


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def test_fleet_table_wire_golden_vectors(fixture_data):
    for case in fixture_data["cases"]:
        got = table_from_core(case["coreInput"])
        assert got == case["expectedTableWire"], case["name"]
