"""Golden vectors: BFF fleet table wire vs test-fixtures/fleet-table-wire.json."""

import json
from pathlib import Path

import pytest
from api.serialization.turn import turn_info_from_json
from bff.analytics.fleet import table_from_core

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "test-fixtures" / "fleet-table-wire.json"
TURN_SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "api" / "api" / "storage" / "assets" / "turn_sample.json"
)


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sample_turn():
    with open(TURN_SAMPLE_PATH) as handle:
        return turn_info_from_json(json.load(handle))


def test_fleet_table_wire_golden_vectors(fixture_data, sample_turn):
    for case in fixture_data["cases"]:
        got = table_from_core(case["coreInput"], turn=sample_turn)
        assert got == case["expectedTableWire"], case["name"]
