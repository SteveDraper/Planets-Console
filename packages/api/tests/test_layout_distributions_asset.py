"""Tests for homeworld layout distribution asset distill + load."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.layout_distributions_asset import (
    COST_MODEL_NORMAL_NEG_LOG_DENSITY,
    LAYOUT_DISTRIBUTIONS_FILENAME,
    SCHEMA_VERSION,
    distill_layout_distributions_from_report,
    distill_metric_from_histogram,
    layout_distributions_asset_from_json,
    layout_distributions_asset_to_json,
    load_layout_distributions_asset,
    write_layout_distributions_asset,
)
from api.analytics.homeworld_locator_assets import HomeworldLocator
from api.concepts.game_category import GameCategory

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "homeworld_layout_distributions"


def test_distill_metric_trims_zeros_and_fits_normal() -> None:
    # Bins 0-10 and 10-20 empty; mass in 20-30 and 30-40 only.
    counts = [0, 0, 3, 1, 0]
    metric = distill_metric_from_histogram(counts, bin_width=10)

    assert metric.support_min == 20.0
    assert metric.support_max == 40.0
    assert metric.sample_count == 4
    # Midpoints 25 (x3) and 35 (x1) → mean 27.5
    assert metric.mean == pytest.approx(27.5)
    assert metric.std > 0.0
    assert metric.neg_log_density(metric.mean) < metric.neg_log_density(metric.mean + 20.0)


def test_distill_metric_rejects_empty_positive_mass() -> None:
    with pytest.raises(ValueError, match="no positive counts"):
        distill_metric_from_histogram([0, 0, 0], bin_width=10)


def test_distill_from_fixture_report_yields_band_edges(tmp_path: Path) -> None:
    report = json.loads((FIXTURES_DIR / "sample_report.json").read_text())
    asset = distill_layout_distributions_from_report(report)

    epic_inner, epic_outer = asset.center_distance_band(GameCategory.EPIC)
    standard_inner, standard_outer = asset.center_distance_band("standard")

    assert (epic_inner, epic_outer) == (520.0, 560.0)
    assert (standard_inner, standard_outer) == (310.0, 340.0)
    assert asset.cost_model == COST_MODEL_NORMAL_NEG_LOG_DENSITY
    assert asset.schema_version == SCHEMA_VERSION

    epic = asset.for_category(GameCategory.EPIC)
    assert epic.center_distance.sample_count == 10
    assert epic.neighbor_separation.support_min == 430.0
    assert epic.neighbor_separation.support_max == 460.0
    assert epic.center_distance.mean > epic.center_distance.support_min
    assert epic.center_distance.std > 0.0

    # Round-trip JSON preserves band edges used by paint.
    written = write_layout_distributions_asset(asset, path=tmp_path / "layout.json")
    reloaded = load_layout_distributions_asset(written)
    assert reloaded.center_distance_band("epic") == (520.0, 560.0)
    assert (
        layout_distributions_asset_to_json(reloaded)["categories"]["epic"]["centerDistance"][
            "supportMin"
        ]
        == 520.0
    )
    assert layout_distributions_asset_to_json(reloaded)["costModel"] == (
        COST_MODEL_NORMAL_NEG_LOG_DENSITY
    )


def test_loader_rejects_unsupported_schema_version() -> None:
    report = json.loads((FIXTURES_DIR / "sample_report.json").read_text())
    asset = distill_layout_distributions_from_report(report)
    payload = layout_distributions_asset_to_json(asset)
    payload["schemaVersion"] = 999
    with pytest.raises(ValueError, match="schemaVersion"):
        layout_distributions_asset_from_json(payload)


def test_shipped_layout_distributions_asset_loads_and_matches_known_bands() -> None:
    """Committed asset distilled from local/homeworld_distributions.json histograms."""
    asset_path = HomeworldLocator.assets_dir() / LAYOUT_DISTRIBUTIONS_FILENAME
    assert asset_path.is_file()

    asset = load_layout_distributions_asset()
    assert asset.schema_version == SCHEMA_VERSION
    assert asset.cost_model == COST_MODEL_NORMAL_NEG_LOG_DENSITY
    epic_inner, epic_outer = asset.center_distance_band(GameCategory.EPIC)
    standard_inner, standard_outer = asset.center_distance_band(GameCategory.STANDARD)

    # Observed raw mins/maxes were ~524–885 (epic) and ~320–579 (standard);
    # 10 LY bin support extremes after trim are the paint band.
    assert epic_inner == 520.0
    assert epic_outer == 890.0
    assert standard_inner == 310.0
    assert standard_outer == 580.0

    for category in ("epic", "standard"):
        tables = asset.for_category(category)
        assert tables.center_distance.sample_count > 0
        assert tables.neighbor_separation.sample_count > 0
        assert tables.center_distance.std > 0.0
        assert tables.neighbor_separation.std > 0.0
        assert tables.neighbor_separation.support_min < tables.neighbor_separation.support_max
