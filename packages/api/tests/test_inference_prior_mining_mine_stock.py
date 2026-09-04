"""Tests for mine-stock observation extraction and sibling asset merge."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml
from api.analytics.military_score_inference.prior_mining.mine_stock import (
    MineStockAccumulation,
    accumulation_mine_stock_report_section,
    create_empty_mine_stock_asset,
    extract_mine_stock_sample,
    load_mine_stock_asset,
    merge_mine_stock_accumulation_into_asset,
    write_mine_stock_asset,
)
from api.concepts.game_category import GAME_CATEGORY_RULES_VERSION, GameCategory
from api.models.space import Minefield

from tests.inference_corpus.fixtures import load_turn_fixture

PLAYER_ID = 2
RACE_ID = 2
HOST_TURN = 2


def _minefield(
    *,
    field_id: int,
    ownerid: int,
    units: int,
    isweb: bool = False,
    ishidden: bool = False,
    infoturn: int = HOST_TURN,
) -> Minefield:
    return Minefield(
        id=field_id,
        ownerid=ownerid,
        isweb=isweb,
        ishidden=ishidden,
        units=units,
        infoturn=infoturn,
        friendlycode="???",
        x=0,
        y=0,
        radius=1,
    )


def _turn_with_fields(*fields: Minefield):
    turn = load_turn_fixture("628580/1/turns/2.json")
    return replace(turn, minefields=list(fields))


def test_extract_ignores_other_owners_zero_units_and_counts_web_split():
    turn = _turn_with_fields(
        _minefield(field_id=1, ownerid=PLAYER_ID, units=400),
        _minefield(field_id=2, ownerid=PLAYER_ID, units=100, isweb=True),
        _minefield(field_id=3, ownerid=PLAYER_ID, units=0),
        _minefield(field_id=4, ownerid=99, units=9000, infoturn=1),
        _minefield(field_id=5, ownerid=PLAYER_ID, units=50, ishidden=True),
    )
    sample = extract_mine_stock_sample(
        turn,
        player_id=PLAYER_ID,
        race_id=RACE_ID,
        host_turn=HOST_TURN,
    )
    assert sample.total_units == 550
    assert sample.field_count == 3
    assert sample.per_field_units == (400, 100, 50)
    assert sample.web_total_units == 100
    assert sample.web_field_count == 1
    assert sample.web_per_field_units == (100,)
    assert sample.normal_total_units == 450
    assert sample.normal_field_count == 2
    assert sample.normal_per_field_units == (400, 50)
    assert sample.infoturn_mismatches == 0


def test_extract_empty_stock_increments_zero_totals_without_per_field_zero():
    turn = _turn_with_fields(
        _minefield(field_id=1, ownerid=PLAYER_ID, units=0),
        _minefield(field_id=2, ownerid=7, units=800, infoturn=1),
    )
    sample = extract_mine_stock_sample(
        turn,
        player_id=PLAYER_ID,
        race_id=RACE_ID,
        host_turn=HOST_TURN,
    )
    assert sample.total_units == 0
    assert sample.field_count == 0
    assert sample.per_field_units == ()
    assert sample.web_total_units == 0
    assert sample.normal_total_units == 0

    accumulation = MineStockAccumulation()
    accumulation.add_sample(sample)
    cell = accumulation.histograms[RACE_ID][HOST_TURN]
    assert cell["totalUnits"][0] == 1
    assert cell["fieldCount"][0] == 1
    assert "perFieldUnits" not in cell or cell["perFieldUnits"] == {}
    assert accumulation.zero_stock_count == 1


def test_extract_counts_stale_own_infoturn_mismatch():
    turn = _turn_with_fields(
        _minefield(field_id=1, ownerid=PLAYER_ID, units=10, infoturn=1),
        _minefield(field_id=2, ownerid=PLAYER_ID, units=20, infoturn=HOST_TURN),
    )
    sample = extract_mine_stock_sample(
        turn,
        player_id=PLAYER_ID,
        race_id=RACE_ID,
        host_turn=HOST_TURN,
    )
    assert sample.infoturn_mismatches == 1
    assert sample.total_units == 30


def _sample_accumulation() -> MineStockAccumulation:
    accumulation = MineStockAccumulation()
    turn = _turn_with_fields(
        _minefield(field_id=1, ownerid=PLAYER_ID, units=400),
        _minefield(field_id=2, ownerid=PLAYER_ID, units=100, isweb=True),
    )
    accumulation.add_sample(
        extract_mine_stock_sample(
            turn,
            player_id=PLAYER_ID,
            race_id=RACE_ID,
            host_turn=HOST_TURN,
        )
    )
    return accumulation


def test_merge_and_write_round_trips_histograms_and_contributing_ids(tmp_path: Path):
    empty = create_empty_mine_stock_asset(GameCategory.STANDARD)
    merged = merge_mine_stock_accumulation_into_asset(
        empty,
        _sample_accumulation(),
        provenance_game_ids=(628580, 628580, 1),
    )
    output = tmp_path / "mine_stock_standard.yaml"
    write_mine_stock_asset(output, merged)

    reloaded = load_mine_stock_asset(output)
    assert reloaded.category == "standard"
    assert reloaded.game_category_rules_version == GAME_CATEGORY_RULES_VERSION
    assert reloaded.contributing_game_ids == (628580, 1)
    cell = reloaded.histograms[RACE_ID][HOST_TURN]
    assert cell["totalUnits"][500] == 1
    assert cell["fieldCount"][2] == 1
    assert cell["perFieldUnits"][400] == 1
    assert cell["perFieldUnits"][100] == 1
    assert cell["webTotalUnits"][100] == 1
    assert cell["normalTotalUnits"][400] == 1
    text = output.read_text(encoding="utf-8")
    assert "histogram:" in text
    assert "contributingGameIds:" in text


def test_write_includes_row_counts_matching_total_units_sample_counts(tmp_path: Path):
    empty = create_empty_mine_stock_asset(GameCategory.STANDARD)
    merged = merge_mine_stock_accumulation_into_asset(
        empty,
        _sample_accumulation(),
        provenance_game_ids=(628580,),
    )
    output = tmp_path / "mine_stock_standard.yaml"
    write_mine_stock_asset(output, merged)
    text = output.read_text(encoding="utf-8")
    assert text.index("rowCounts:") < text.index("mineStock:")
    document = yaml.safe_load(text)
    expected = int(sum(merged.histograms[RACE_ID][HOST_TURN]["totalUnits"].values()))
    assert document["rowCounts"]["byRace"][RACE_ID]["byTurn"][HOST_TURN] == expected
    assert expected == 1


def test_write_uses_compact_flow_histogram_maps(tmp_path: Path):
    empty = create_empty_mine_stock_asset(GameCategory.STANDARD)
    merged = merge_mine_stock_accumulation_into_asset(
        empty,
        _sample_accumulation(),
        provenance_game_ids=(628580,),
    )
    output = tmp_path / "mine_stock_standard.yaml"
    write_mine_stock_asset(output, merged)
    text = output.read_text(encoding="utf-8")
    histogram_lines = [line for line in text.splitlines() if "histogram:" in line]
    assert histogram_lines
    assert all("histogram: {" in line for line in histogram_lines)
    assert "histogram:\n" not in text


def test_load_accepts_block_style_histogram_yaml(tmp_path: Path):
    path = tmp_path / "mine_stock_standard.yaml"
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "category: standard",
                f"gameCategoryRulesVersion: {GAME_CATEGORY_RULES_VERSION}",
                "mineStock:",
                "  byRace:",
                "    2:",
                "      byTurn:",
                "        2:",
                "          totalUnits:",
                "            histogram:",
                "              0: 105",
                "              33: 1",
                "          fieldCount:",
                "            histogram:",
                "              1: 106",
                "contributingGameIds:",
                "  - 628580",
                "",
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_mine_stock_asset(path)
    assert loaded.category == "standard"
    assert loaded.contributing_game_ids == (628580,)
    cell = loaded.histograms[2][2]
    assert cell["totalUnits"][0] == 105
    assert cell["totalUnits"][33] == 1
    assert cell["fieldCount"][1] == 106


def test_load_ignores_missing_and_stale_row_counts(tmp_path: Path):
    missing_path = tmp_path / "mine_stock_missing_row_counts.yaml"
    missing_path.write_text(
        "\n".join(
            [
                "version: 1",
                "category: standard",
                f"gameCategoryRulesVersion: {GAME_CATEGORY_RULES_VERSION}",
                "mineStock:",
                "  byRace:",
                "    2:",
                "      byTurn:",
                "        2:",
                "          totalUnits:",
                "            histogram: {0: 3}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    missing = load_mine_stock_asset(missing_path)
    assert missing.histograms[2][2]["totalUnits"][0] == 3

    stale_path = tmp_path / "mine_stock_stale_row_counts.yaml"
    stale_path.write_text(
        "\n".join(
            [
                "version: 1",
                "category: standard",
                f"gameCategoryRulesVersion: {GAME_CATEGORY_RULES_VERSION}",
                "rowCounts:",
                "  byRace:",
                "    2:",
                "      byTurn:",
                "        2: 999",
                "mineStock:",
                "  byRace:",
                "    2:",
                "      byTurn:",
                "        2:",
                "          totalUnits:",
                "            histogram: {0: 3}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    stale = load_mine_stock_asset(stale_path)
    assert stale.histograms[2][2]["totalUnits"][0] == 3


def test_report_section_keeps_row_counts_without_full_mine_stock():
    section = accumulation_mine_stock_report_section(_sample_accumulation())
    assert "mineStock" not in section
    assert section["sample_count"] == 1
    assert section["zero_stock_count"] == 0
    assert section["infoturn_mismatches"] == 0
    assert section["row_counts"][str(RACE_ID)][str(HOST_TURN)] == 1
