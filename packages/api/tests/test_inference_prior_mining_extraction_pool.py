"""Tests for parallel prior mining extraction."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from api.analytics.military_score_inference.prior_mining.accumulation import (
    PriorMiningAccumulation,
)
from api.analytics.military_score_inference.prior_mining.component_name_catalog import (
    ComponentNameCatalogBuilder,
)
from api.analytics.military_score_inference.prior_mining.extraction_pool import (
    _apply_extraction_row_result,
    enumerate_extraction_work_units,
    run_extractions_for_game,
)
from api.analytics.military_score_inference.prior_mining.extraction_worker import (
    ExtractionRowResult,
    ExtractionSkipReason,
    ExtractionWorkUnit,
    extract_extraction_work_unit,
)
from api.analytics.military_score_inference.prior_mining.report import PriorMiningReport
from api.serialization.game import game_info_from_json

from tests.inference_corpus.fixtures import load_turn_fixture

FIXTURE_INFO = (
    Path(__file__).resolve().parent / "fixtures" / "inference_corpus" / "628580" / "info.json"
)


def _load_game_info():
    return game_info_from_json(json.loads(FIXTURE_INFO.read_text(encoding="utf-8")))


def _mock_turn_load_for_host_turn_2() -> MagicMock:
    turns = {
        2: load_turn_fixture("628580/1/turns/2.json"),
        3: load_turn_fixture("628580/1/turns/3.json"),
    }
    turn_load = MagicMock()
    turn_load.get_turn_info.side_effect = lambda _gid, _perspective, turn_number: turns[turn_number]
    turn_load.list_stored_turn_numbers.return_value = [2, 3]
    turn_load.list_stored_turn_perspectives.return_value = [1]
    return turn_load


def test_enumerate_extraction_work_units_respects_stored_turn_pairs() -> None:
    game_info = _load_game_info()
    turn_load = MagicMock()
    turn_load.list_stored_turn_numbers.return_value = [2, 3]

    units = enumerate_extraction_work_units(game_info, 628580, turn_load)

    assert units
    assert all(unit.game_id == 628580 for unit in units)
    assert all(unit.host_turn == 2 for unit in units)
    assert all(unit.perspective == unit.player_id for unit in units)


def test_extract_extraction_work_unit_returns_row_for_fixture() -> None:
    unit = ExtractionWorkUnit(
        game_id=628580,
        player_id=2,
        perspective=2,
        host_turn=2,
        race_id=2,
    )
    result = extract_extraction_work_unit(
        turn_load=_mock_turn_load_for_host_turn_2(),
        unit=unit,
    )
    assert result.outcome in {"ok", "skip"}
    assert result.name_catalog is not None
    if result.outcome == "skip":
        assert result.skip_reason in {
            ExtractionSkipReason.ADJUNCT,
            ExtractionSkipReason.MISSING_SCORE,
        }
    else:
        assert result.extraction is not None


def test_apply_extraction_row_result_records_errors_without_raising() -> None:
    accumulation = PriorMiningAccumulation()
    name_catalog = ComponentNameCatalogBuilder()
    report = PriorMiningReport(dry_run=True)
    unit = ExtractionWorkUnit(
        game_id=628580,
        player_id=2,
        perspective=2,
        host_turn=2,
        race_id=2,
    )
    from api.analytics.military_score_inference.prior_mining.extraction_pool import (
        ExtractionRunSummary,
    )

    summary = ExtractionRunSummary()
    _apply_extraction_row_result(
        ExtractionRowResult(unit=unit, outcome="error", error_message="boom"),
        accumulation=accumulation,
        name_catalog=name_catalog,
        report=report,
        summary=summary,
    )
    assert summary.extraction_errors == 1
    assert report.extraction_errors[0].message == "boom"


def test_run_extractions_for_game_serial_matches_direct_unit_extract(tmp_path: Path) -> None:
    del tmp_path
    game_info = _load_game_info()
    turn_load = _mock_turn_load_for_host_turn_2()
    units = enumerate_extraction_work_units(game_info, 628580, turn_load)
    assert units

    direct = PriorMiningAccumulation()
    for unit in units:
        result = extract_extraction_work_unit(turn_load=turn_load, unit=unit)
        if result.outcome == "ok" and result.extraction is not None:
            direct.add_player_host_turn(result.extraction)

    pooled = PriorMiningAccumulation()
    report = PriorMiningReport(dry_run=True)
    name_catalog = ComponentNameCatalogBuilder()
    summary = run_extractions_for_game(
        game_info=game_info,
        game_id=628580,
        turn_load=turn_load,
        storage_root=Path("."),
        workers=1,
        accumulation=pooled,
        name_catalog=name_catalog,
        report=report,
    )
    assert summary.units_ok == sum(
        1
        for unit in units
        if extract_extraction_work_unit(turn_load=turn_load, unit=unit).outcome == "ok"
    )
    assert pooled.hull_counts == direct.hull_counts
    assert pooled.aggregate_histograms == direct.aggregate_histograms
