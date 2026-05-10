"""Tests for Core analytics modules and registry dispatch."""

import json
from pathlib import Path

import pytest
from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.base_map import get_base_map
from api.analytics.scores import get_scores_table
from api.errors import ValidationError
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as f:
        return turn_info_from_json(json.load(f))


def test_base_map_module_returns_nodes(sample_turn):
    data = get_base_map(sample_turn)
    assert data["analyticId"] == "base-map"
    assert data["edges"] == []
    assert data["nodes"][0]["id"].startswith("p")


def test_scores_module_returns_structured_score_rows(sample_turn):
    data = get_scores_table(sample_turn)
    assert data["analyticId"] == "scores"
    assert data["rows"][0]["racePlayer"] == "koshling"
    assert data["rows"][0]["military"] == {"value": 2509092, "change": -53869}


def test_registry_rejects_unknown_analytic(sample_turn):
    with pytest.raises(ValidationError, match="Unknown analytic_id"):
        get_turn_analytic("missing", sample_turn, TurnAnalyticsOptions())
