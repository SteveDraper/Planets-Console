"""Tests for Core analytics modules and registry dispatch."""

import json
from pathlib import Path

import pytest
from api.analytics import TURN_ANALYTIC_CATALOG, TurnAnalyticsOptions, get_turn_analytic
from api.analytics.base_map import get_base_map
from api.analytics.registry import TURN_ANALYTICS
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
    assert len(data["nodes"][0]["normalWellCells"]) == 29


def test_scores_module_returns_structured_score_rows(sample_turn):
    data = get_scores_table(sample_turn)
    assert data["analyticId"] == "scores"
    assert data["rows"][0]["racePlayer"] == "koshling"
    assert data["rows"][0]["military"] == {"value": 2509092, "change": -53869}
    assert "inference" not in data["rows"][0]


def test_registry_scores_dispatch_unchanged_without_inference_option(sample_turn):
    data = get_turn_analytic("scores", sample_turn, TurnAnalyticsOptions())
    assert data["analyticId"] == "scores"
    assert "inference" not in data["rows"][0]


def test_registry_rejects_unknown_analytic(sample_turn):
    with pytest.raises(ValidationError, match="Unknown analytic_id"):
        get_turn_analytic("missing", sample_turn, TurnAnalyticsOptions())


def test_turn_analytic_registrations_derive_catalog_and_handlers():
    from api.analytics.registrations import TURN_ANALYTIC_REGISTRATIONS

    assert TURN_ANALYTIC_CATALOG == tuple(
        registration.catalog_entry for registration in TURN_ANALYTIC_REGISTRATIONS
    )
    assert list(TURN_ANALYTICS) == [
        registration.catalog_entry.id for registration in TURN_ANALYTIC_REGISTRATIONS
    ]
    for registration in TURN_ANALYTIC_REGISTRATIONS:
        assert TURN_ANALYTICS[registration.catalog_entry.id] is registration.handler


def test_dict_aligned_with_turn_analytic_catalog_reports_mismatch():
    from api.analytics.catalog import dict_aligned_with_turn_analytic_catalog

    with pytest.raises(RuntimeError, match="Core handlers"):
        dict_aligned_with_turn_analytic_catalog(
            {"not-in-catalog": object()},
            role="Core handlers",
        )


def test_validate_turn_analytic_registrations_rejects_empty_tuple():
    from api.analytics.registration import validate_turn_analytic_registrations

    with pytest.raises(RuntimeError, match="must not be empty"):
        validate_turn_analytic_registrations(())


def test_validate_turn_analytic_registrations_rejects_duplicate_ids():
    from api.analytics.catalog import TurnAnalyticCatalogEntry
    from api.analytics.registration import (
        TurnAnalyticRegistration,
        validate_turn_analytic_registrations,
    )

    catalog_entry = TurnAnalyticCatalogEntry(
        id="duplicate-id",
        name="Duplicate",
        supports_table=True,
        supports_map=False,
        type="selectable",
    )

    def handler(_ctx):
        return {"analyticId": "duplicate-id"}

    registrations = (
        TurnAnalyticRegistration(catalog_entry=catalog_entry, handler=handler),
        TurnAnalyticRegistration(catalog_entry=catalog_entry, handler=handler),
    )

    with pytest.raises(RuntimeError, match="Duplicate"):
        validate_turn_analytic_registrations(registrations)
