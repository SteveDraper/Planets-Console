"""Tests for commented prior weight asset output and bootstrap."""

from __future__ import annotations

from pathlib import Path

from api.analytics.military_score_inference.prior_mining.accumulation import (
    PriorMiningAccumulation,
)
from api.analytics.military_score_inference.prior_mining.asset_write import (
    render_commented_prior_weights_yaml,
)
from api.analytics.military_score_inference.prior_mining.component_name_catalog import (
    ComponentNameCatalogBuilder,
)
from api.analytics.military_score_inference.prior_mining.merge import (
    load_or_bootstrap_asset,
    merge_accumulation_into_asset,
    write_prior_weights_asset,
)
from api.analytics.military_score_inference.prior_mining.observations import ShipBuildObservation
from api.analytics.military_score_inference.prior_weights_asset import (
    create_empty_prior_weights_asset,
    load_prior_weights_asset,
)
from api.concepts.game_category import GameCategory

from tests.inference_corpus.fixtures import load_turn_fixture


def _catalog_from_turn_fixture(relative_path: str):
    builder = ComponentNameCatalogBuilder()
    builder.absorb_turn(load_turn_fixture(relative_path))
    return builder.build()


def test_load_or_bootstrap_asset_returns_empty_when_file_missing(tmp_path: Path):
    asset = load_or_bootstrap_asset(GameCategory.STANDARD, base_dir=tmp_path)
    assert asset.category == GameCategory.STANDARD
    assert asset.hulls["before_ship_limit"]["global"] == {}
    assert asset.contributing_game_ids == ()


def test_merge_and_write_bootstraps_missing_category_file(tmp_path: Path):
    asset = create_empty_prior_weights_asset(GameCategory.STANDARD)
    accumulation = PriorMiningAccumulation()
    accumulation.add_ship_build(
        ShipBuildObservation(
            hull_id=24,
            engine_id=1,
            beam_id=1,
            torpedo_id=1,
            beam_count=2,
            launcher_count=0,
            hull_category="beam_ship",
            ship_limit_band="before_ship_limit",
            race_id=2,
            hull_beam_slots=2,
            hull_launcher_slots=0,
        ),
    )

    merged = merge_accumulation_into_asset(
        asset,
        accumulation,
        provenance_game_ids=(671041,),
    )
    output_path = tmp_path / "prior_weights_standard.yaml"
    write_prior_weights_asset(
        output_path,
        merged,
        name_catalog=_catalog_from_turn_fixture("628580/1/turns/3.json"),
    )
    assert output_path.is_file()

    reloaded = load_prior_weights_asset(output_path, require_complete_aggregates=False)
    assert reloaded.hulls["before_ship_limit"]["global"][24] == 1
    assert 671041 in reloaded.contributing_game_ids

    text = output_path.read_text(encoding="utf-8")
    assert "Inference build prior for the" in text
    assert "Serpent Class Escort" in text
    assert "StarDrive 1" in text


def test_component_name_catalog_builder_accumulates_from_turns():
    builder = ComponentNameCatalogBuilder()
    assert builder.hulls == {}

    builder.absorb_turn(load_turn_fixture("628580/1/turns/3.json"))
    assert builder.hulls[24] == "Serpent Class Escort"
    assert builder.engines[1] == "StarDrive 1"
    assert builder.torpedoes[10] == "Mark 8 Photon"

    builder.absorb_turn(load_turn_fixture("628580/1/turns/2.json"))
    catalog = builder.build()
    assert catalog.hulls[24] == "Serpent Class Escort"


def test_render_commented_yaml_includes_aggregate_none_bin_comment():
    from dataclasses import replace

    from api.analytics.military_score_inference.prior_weights_asset import HistogramAggregate

    asset = replace(
        create_empty_prior_weights_asset(GameCategory.STANDARD),
        aggregates={
            "before_ship_limit": {
                "planet_defense_posts_added_total": HistogramAggregate(histogram={0: 3, 5: 2}),
            },
            "after_ship_limit": {},
        },
    )
    text = render_commented_prior_weights_yaml(
        asset,
        name_catalog=_catalog_from_turn_fixture("628580/1/turns/3.json"),
    )
    assert "none-bin occurrence pseudo-count" in text
    assert "magnitude (discrete total)" in text
