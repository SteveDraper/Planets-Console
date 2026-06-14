"""Tests for prior mining accumulation and asset merge."""

from __future__ import annotations

from pathlib import Path

from api.analytics.military_score_inference.prior_mining.accumulation import (
    PriorMiningAccumulation,
)
from api.analytics.military_score_inference.prior_mining.component_name_catalog import (
    ComponentNameCatalogBuilder,
)
from api.analytics.military_score_inference.prior_mining.merge import (
    accumulation_mining_report_sections,
    merge_accumulation_into_asset,
    write_prior_weights_asset,
)
from api.analytics.military_score_inference.prior_mining.observations import ShipBuildObservation
from api.analytics.military_score_inference.prior_weights_asset import (
    load_prior_weights_asset,
    parse_prior_weights_document,
)

from tests.fixtures.hand_seeded_prior_weights import HAND_SEEDED_STANDARD_PRIOR_PATH
from tests.inference_corpus.fixtures import load_turn_fixture
from tests.test_military_score_inference_prior_weights_asset import _minimal_prior_weights_document


def _catalog_from_turn_fixture(relative_path: str):
    builder = ComponentNameCatalogBuilder()
    builder.absorb_turn(load_turn_fixture(relative_path))
    return builder.build()


def test_merge_accumulation_adds_counts_and_contributing_game_ids(tmp_path: Path):
    source = HAND_SEEDED_STANDARD_PRIOR_PATH
    asset = load_prior_weights_asset(source)
    before_hull = asset.hulls["before_ship_limit"]["global"].get(13, 0)

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
    accumulation.add_aggregate_sample("planet_defense_posts_added_total", "before_ship_limit", 0)
    accumulation.add_aggregate_sample("planet_defense_posts_added_total", "before_ship_limit", 5)

    merged = merge_accumulation_into_asset(
        asset,
        accumulation,
        provenance_game_ids=(999001,),
    )
    assert merged.contributing_game_ids[-1] == 999001
    assert merged.hulls["before_ship_limit"]["global"][13] == before_hull + 1
    histogram = merged.aggregates["before_ship_limit"]["planet_defense_posts_added_total"].histogram
    assert histogram[0] >= 1
    assert histogram[5] >= 1

    output_path = tmp_path / "prior_weights_standard.yaml"
    write_prior_weights_asset(
        output_path,
        merged,
        name_catalog=_catalog_from_turn_fixture("628580/1/turns/3.json"),
    )
    reloaded = load_prior_weights_asset(output_path)
    assert 999001 in reloaded.contributing_game_ids


def test_merge_accumulation_appends_rejected_game_ids_to_provenance(tmp_path: Path):
    source = HAND_SEEDED_STANDARD_PRIOR_PATH
    asset = load_prior_weights_asset(source)
    before_hull = asset.hulls["before_ship_limit"]["global"].get(13, 0)

    merged = merge_accumulation_into_asset(
        asset,
        PriorMiningAccumulation(),
        provenance_game_ids=(888002,),
    )
    assert 888002 in merged.contributing_game_ids
    assert merged.hulls["before_ship_limit"]["global"].get(13, 0) == before_hull

    output_path = tmp_path / "prior_weights_standard.yaml"
    write_prior_weights_asset(
        output_path,
        merged,
        name_catalog=_catalog_from_turn_fixture("628580/1/turns/3.json"),
    )
    reloaded = load_prior_weights_asset(output_path)
    assert 888002 in reloaded.contributing_game_ids


def test_accumulation_mining_report_sections_includes_histogram_magnitudes():
    accumulation = PriorMiningAccumulation()
    accumulation.add_aggregate_sample("ship_torps_loaded_9", "before_ship_limit", 0)
    accumulation.add_aggregate_sample("ship_torps_loaded_9", "before_ship_limit", 9)
    accumulation.add_aggregate_sample("ship_torps_loaded_9", "before_ship_limit", 9)

    sections = accumulation_mining_report_sections(accumulation)
    histogram = sections["aggregate_histograms"]["before_ship_limit"]["ship_torps_loaded_9"][
        "histogram"
    ]
    assert histogram["0"] == 1
    assert histogram["9"] == 2


def test_merge_accumulation_into_report_merges_ship_and_histogram_sections():
    from api.analytics.military_score_inference.prior_mining.report import (
        PriorMiningReport,
        merge_accumulation_into_report,
    )

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
    accumulation.add_aggregate_sample("planet_defense_posts_added_total", "before_ship_limit", 5)

    report = PriorMiningReport(dry_run=True)
    merge_accumulation_into_report(report, accumulation)

    assert report.ship_builds["total_ship_builds"] == 1
    assert report.ship_builds["hulls"]["before_ship_limit"]["global"][13] == 1
    histogram = report.aggregate_histograms["before_ship_limit"][
        "planet_defense_posts_added_total"
    ]["histogram"]
    assert histogram["5"] == 1


def test_parse_contributing_game_ids_optional():
    document = _minimal_prior_weights_document(contributingGameIds=[628580, 673864])
    asset = parse_prior_weights_document(document)
    assert asset.contributing_game_ids == (628580, 673864)
