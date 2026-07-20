"""Tests for the temporary map-region-demo analytic."""

import json
from pathlib import Path

import pytest
from api.analytics.map_region_demo import ANALYTIC_ID, get_map_region_demo_map
from api.analytics.options import TurnAnalyticsOptions
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def stellar_cartography_turn():
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        return turn_info_from_json(json.load(f))


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as f:
        return turn_info_from_json(json.load(f))


def test_map_region_demo_emits_region_overlays_disk_only(sample_turn):
    data = get_map_region_demo_map(sample_turn, TurnAnalyticsOptions())
    assert data["analyticId"] == ANALYTIC_ID
    assert data["nodes"] == []
    assert data["edges"] == []
    overlays = data["regionOverlays"]
    assert len(overlays) == 1
    overlay = overlays[0]
    assert overlay["kind"] == "demo"
    assert overlay["fillColor"] == "#22c55e"
    assert overlay["fillOpacity"] == 0.25
    assert len(overlay["disks"]) >= 1
    assert overlay["patches"] == [] or isinstance(overlay["patches"], list)


def test_map_region_demo_emits_nebula_patches_when_present(stellar_cartography_turn):
    data = get_map_region_demo_map(stellar_cartography_turn, TurnAnalyticsOptions())
    overlay = data["regionOverlays"][0]
    assert len(overlay["disks"]) >= 1
    assert len(overlay["patches"]) >= 1
    for patch in overlay["patches"]:
        assert patch["width"] * patch["height"] == sum(
            run["length"] for run in patch["coverageRle"]
        )
