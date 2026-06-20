"""Tests for Core analytics modules and registry dispatch."""

import json
from pathlib import Path

import pytest
from api.analytics import TURN_ANALYTIC_CATALOG, TurnAnalyticsOptions, get_turn_analytic
from api.analytics.base_map import get_base_map
from api.analytics.compute_context import AnalyticComputeContext
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


def test_get_turn_analytic_passes_diagnostics_on_context(sample_turn, monkeypatch):
    from api.diagnostics import DiagnosticNode

    diagnostics = DiagnosticNode(name="test-root")
    captured: dict[str, object] = {}

    def capture_handler(ctx: AnalyticComputeContext) -> dict:
        captured["diagnostics"] = ctx.diagnostics
        return {"analyticId": "scores"}

    monkeypatch.setitem(TURN_ANALYTICS, "scores", capture_handler)
    get_turn_analytic("scores", sample_turn, TurnAnalyticsOptions(diagnostics=diagnostics))
    assert captured["diagnostics"] is diagnostics


def test_turn_analytic_registrations_derive_catalog_and_handlers():
    from api.analytics.registry import TURN_ANALYTIC_REGISTRATIONS

    assert TURN_ANALYTIC_CATALOG == tuple(
        registration.catalog_entry for registration in TURN_ANALYTIC_REGISTRATIONS
    )
    assert list(TURN_ANALYTICS) == [
        registration.catalog_entry.id for registration in TURN_ANALYTIC_REGISTRATIONS
    ]
    for registration in TURN_ANALYTIC_REGISTRATIONS:
        assert registration.catalog_entry.id in TURN_ANALYTICS
        assert callable(registration.compute)
        assert registration.export_catalog.analytic_id == registration.catalog_entry.id


def test_validate_turn_analytic_registrations_rejects_empty_tuple():
    from api.analytics.registration import validate_turn_analytic_registrations

    with pytest.raises(RuntimeError, match="must not be empty"):
        validate_turn_analytic_registrations(())


def test_validate_turn_analytic_registrations_rejects_duplicate_ids():
    from api.analytics.catalog import TurnAnalyticCatalogEntry
    from api.analytics.exports.empty import empty_export_catalog_for
    from api.analytics.registration import (
        TurnAnalyticRegistration,
        validate_turn_analytic_registrations,
    )

    entry = TurnAnalyticCatalogEntry(
        id="duplicate-id",
        name="Duplicate",
        supports_table=True,
        supports_map=False,
        type="selectable",
    )

    def compute(_ctx: AnalyticComputeContext) -> dict:
        return {"analyticId": "duplicate-id"}

    export_catalog = empty_export_catalog_for(entry.id)
    registrations = (
        TurnAnalyticRegistration(
            catalog_entry=entry,
            compute=compute,
            export_catalog=export_catalog,
        ),
        TurnAnalyticRegistration(
            catalog_entry=entry,
            compute=compute,
            export_catalog=export_catalog,
        ),
    )

    with pytest.raises(RuntimeError, match="Duplicate"):
        validate_turn_analytic_registrations(registrations)


def _registration_for_validation(*, compute=None, **catalog_overrides):
    from api.analytics.catalog import TurnAnalyticCatalogEntry
    from api.analytics.exports.empty import empty_export_catalog_for
    from api.analytics.registration import TurnAnalyticRegistration

    catalog_fields = {
        "id": "test-analytic",
        "name": "Test",
        "supports_table": True,
        "supports_map": False,
        "type": "selectable",
    }
    catalog_fields.update(catalog_overrides)
    entry = TurnAnalyticCatalogEntry(**catalog_fields)
    if compute is None:

        def compute(_ctx: AnalyticComputeContext) -> dict:
            return {"analyticId": entry.id}

    return TurnAnalyticRegistration(
        catalog_entry=entry,
        compute=compute,
        export_catalog=empty_export_catalog_for(entry.id),
    )


@pytest.mark.parametrize(
    ("catalog_overrides", "match"),
    [
        ({"id": ""}, "catalog entry id"),
        ({"id": "   "}, "catalog entry id"),
        ({"name": ""}, "catalog entry name"),
        ({"name": "  \t"}, "catalog entry name"),
        ({"type": "invalid"}, "type must be"),
        ({"supports_table": False, "supports_map": False}, "at least one of table or map"),
    ],
)
def test_validate_turn_analytic_registrations_rejects_invalid_catalog_entry(
    catalog_overrides,
    match,
):
    from api.analytics.registration import validate_turn_analytic_registrations

    with pytest.raises(RuntimeError, match=match):
        validate_turn_analytic_registrations((_registration_for_validation(**catalog_overrides),))


def test_validate_turn_analytic_registrations_rejects_non_callable_compute():
    from api.analytics.registration import validate_turn_analytic_registrations

    with pytest.raises(RuntimeError, match="compute must be callable"):
        validate_turn_analytic_registrations((_registration_for_validation(compute=object()),))
