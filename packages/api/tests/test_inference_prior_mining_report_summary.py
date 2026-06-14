"""Tests for prior mining report stdout summary projection."""

from __future__ import annotations

from api.analytics.military_score_inference.prior_mining.accumulation import (
    PriorMiningAccumulation,
)
from api.analytics.military_score_inference.prior_mining.observations import ShipBuildObservation
from api.analytics.military_score_inference.prior_mining.report import (
    PriorMiningReport,
    merge_accumulation_into_report,
)


def test_to_summary_dict_rolls_up_ship_and_aggregate_tables():
    accumulation = PriorMiningAccumulation()
    accumulation.add_ship_build(
        ShipBuildObservation(
            hull_id=13,
            engine_id=9,
            beam_id=3,
            torpedo_id=6,
            beam_count=8,
            launcher_count=6,
            hull_category="battleship",
            ship_limit_band="before_ship_limit",
            race_id=1,
            hull_beam_slots=8,
            hull_launcher_slots=6,
        ),
    )
    accumulation.add_ship_build(
        ShipBuildObservation(
            hull_id=13,
            engine_id=9,
            beam_id=3,
            torpedo_id=6,
            beam_count=8,
            launcher_count=6,
            hull_category="battleship",
            ship_limit_band="before_ship_limit",
            race_id=1,
            hull_beam_slots=8,
            hull_launcher_slots=6,
        ),
    )
    accumulation.add_aggregate_sample("planet_defense_posts_added_total", "before_ship_limit", 0)
    accumulation.add_aggregate_sample("planet_defense_posts_added_total", "before_ship_limit", 5)

    report = PriorMiningReport(dry_run=True)
    merge_accumulation_into_report(report, accumulation)

    summary = report.to_summary_dict()
    assert summary["ship_builds"]["total_ship_builds"] == 2
    hull_summary = summary["ship_builds"]["hulls"]["before_ship_limit"]
    assert hull_summary["unique_keys"] == 2
    assert hull_summary["sample_count"] == 4
    assert summary["ship_builds"]["components"]["before_ship_limit"]["unique_keys"] >= 1
    assert summary["ship_builds"]["components"]["before_ship_limit"]["sample_count"] >= 2
    assert summary["aggregate_histograms"]["before_ship_limit"][
        "planet_defense_posts_added_total"
    ] == {
        "unique_keys": 2,
        "sample_count": 2,
    }
    assert "global" in report.to_dict()["ship_builds"]["hulls"]["before_ship_limit"]
    assert "global" not in summary["ship_builds"]["hulls"]["before_ship_limit"]


def test_to_summary_json_omits_full_histogram_payload():
    report = PriorMiningReport(dry_run=False)
    report.aggregate_histograms = {
        "before_ship_limit": {
            "planet_defense_posts_added_total": {"histogram": {"0": 3, "5": 2}},
        }
    }

    summary = report.to_summary_dict()
    histogram_section = summary["aggregate_histograms"]["before_ship_limit"][
        "planet_defense_posts_added_total"
    ]
    assert histogram_section == {"unique_keys": 2, "sample_count": 5}
    assert (
        "histogram"
        not in summary["aggregate_histograms"]["before_ship_limit"][
            "planet_defense_posts_added_total"
        ]
    )

    full = report.to_dict()
    assert full["aggregate_histograms"]["before_ship_limit"]["planet_defense_posts_added_total"][
        "histogram"
    ] == {"0": 3, "5": 2}
