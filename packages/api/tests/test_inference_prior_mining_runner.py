"""Tests for prior mining runner resilience and checkpoint flush."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

from api.analytics.military_score_inference.prior_mining.discovery import PatternDiscoveryResult
from api.analytics.military_score_inference.prior_mining.extraction_pool import (
    ExtractionRunSummary,
    MineStockRunSummary,
)
from api.analytics.military_score_inference.prior_mining.merge import load_prior_weights_asset
from api.analytics.military_score_inference.prior_mining.mine_stock import (
    create_empty_mine_stock_asset,
)
from api.analytics.military_score_inference.prior_mining.mine_stock_pipeline import (
    MineStockCategoryState,
    process_prepared_mine_stock_game,
)
from api.analytics.military_score_inference.prior_mining.observations import ShipBuildObservation
from api.analytics.military_score_inference.prior_mining.patterns import (
    PriorMiningPattern,
    PriorMiningPatternConfig,
)
from api.analytics.military_score_inference.prior_mining.prefetch import prefetch_and_process_games
from api.analytics.military_score_inference.prior_mining.prepare_game import (
    IncompleteGapDetail,
    PrepareGameResult,
)
from api.analytics.military_score_inference.prior_mining.report import PriorMiningReport
from api.analytics.military_score_inference.prior_mining.runner import (
    CategoryMiningState,
    _mine_pattern,
    run_prior_miner,
)
from api.analytics.military_score_inference.prior_weights_asset import (
    create_empty_prior_weights_asset,
)
from api.concepts.game_category import GameCategory

from tests.fixtures.hand_seeded_prior_weights import HAND_SEEDED_STANDARD_PRIOR_PATH

_PREFETCH_PREPARE = (
    "api.analytics.military_score_inference.prior_mining.prefetch.GamePreparePrefetcher"
)
_PREFETCH_POOL = (
    "api.analytics.military_score_inference.prior_mining.prefetch.ExtractionProcessPool"
)


def _empty_standard_category_state() -> CategoryMiningState:
    return CategoryMiningState(
        asset=create_empty_prior_weights_asset(GameCategory.STANDARD),
        mine_stock=MineStockCategoryState(
            asset=create_empty_mine_stock_asset(GameCategory.STANDARD)
        ),
    )


def _standard_pattern(*, pattern_id: str = "standard-v1", max_games: int = 2) -> PriorMiningPattern:
    return PriorMiningPattern(
        id=pattern_id,
        game_category=GameCategory.STANDARD,
        max_games=max_games,
        min_difficulty=1.0,
        earliest_date="2024-01-01",
    )


def _discovery_result(
    pattern: PriorMiningPattern,
    *,
    games_added: tuple[int, ...] = (),
    games_rejected: tuple[int, ...] = (),
    games_attempted: tuple[int, ...] = (),
) -> PatternDiscoveryResult:
    return PatternDiscoveryResult(
        pattern_id=pattern.id,
        game_category=pattern.game_category,
        candidates_examined=0,
        category_mismatches=0,
        already_contributed=0,
        games_attempted=games_attempted,
        games_rejected=games_rejected,
        games_added=games_added,
        slots_remaining=0,
    )


def _completed_future(result: object) -> Future:
    future: Future = Future()
    future.set_result(result)
    return future


def test_mine_pattern_continues_after_per_game_error():
    pattern = _standard_pattern(max_games=2)
    state = _empty_standard_category_state()
    report = PriorMiningReport(dry_run=True)
    prepare_results = {
        656637: PrepareGameResult(
            game_id=656637,
            outcome="error",
            error_message="Loadall archive entry 'player1-turn9.trn' did not contain valid JSON.",
        ),
        656638: PrepareGameResult(game_id=656638, outcome="ready"),
    }
    mock_prefetcher = MagicMock()
    mock_prefetcher.submit.side_effect = lambda game_id: _completed_future(prepare_results[game_id])
    mock_extraction_pool = MagicMock()
    info = MagicMock()
    info.settings.nominefields = False
    game_service = MagicMock()
    game_service.get_game_info.return_value = info

    with (
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.iter_accepted_games_for_pattern",
            return_value=iter([656637, 656638]),
        ),
        patch(_PREFETCH_PREPARE) as mock_prepare_cls,
        patch(_PREFETCH_POOL) as mock_pool_cls,
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.run_extractions_for_game",
            return_value=ExtractionRunSummary(units_ok=1),
        ),
        patch(
            "api.analytics.military_score_inference.prior_mining.mine_stock_pipeline.run_mine_stock_extractions_for_game",
            return_value=MineStockRunSummary(),
        ),
    ):
        mock_prepare_cls.return_value.__enter__.return_value = mock_prefetcher
        mock_pool_cls.return_value.__enter__.return_value = mock_extraction_pool
        result = _mine_pattern(
            pattern=pattern,
            state=state,
            planets=MagicMock(),
            turn_load=MagicMock(),
            game_service=game_service,
            storage_root=Path(".data"),
            report=report,
            debug=False,
            workers=1,
            loadall_params=None,
        )

    assert mock_prefetcher.submit.call_count == 2
    assert result.games_added == (656638,)
    assert result.games_rejected == (656637,)
    assert len(report.game_mining_errors) == 1
    assert report.game_mining_errors[0].game_id == 656637
    assert 656637 in state.rejected_game_ids
    assert 656638 in state.new_game_ids
    assert {656637, 656638} <= state.mine_stock.game_ids


def test_run_prior_miner_flushes_accumulation_when_pattern_loop_aborts(tmp_path: Path):
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text("version: 1\npatterns: []\n", encoding="utf-8")
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    source = HAND_SEEDED_STANDARD_PRIOR_PATH
    (assets_dir / "prior_weights_standard.yaml").write_text(
        source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    pattern_one = _standard_pattern(pattern_id="p1", max_games=1)
    pattern_two = _standard_pattern(pattern_id="p2", max_games=1)
    config = PriorMiningPatternConfig(version=1, patterns=(pattern_one, pattern_two))

    def fake_mine_pattern(*, pattern, state, **kwargs):
        del kwargs
        state.contributing_game_ids.add(100001)
        state.contributing_game_ids.add(100002)
        state.new_game_ids.append(100001)
        state.rejected_game_ids.append(100002)
        state.accumulation.add_ship_build(
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
        if pattern.id == "p2":
            raise RuntimeError("simulated fatal abort")
        return _discovery_result(pattern, games_added=(100001,), games_attempted=(100001,))

    with (
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.load_prior_mining_patterns",
            return_value=config,
        ),
        patch(
            "api.analytics.military_score_inference.prior_mining.runner._mine_pattern",
            side_effect=fake_mine_pattern,
        ),
    ):
        report = run_prior_miner(
            patterns_path=patterns_path,
            storage_root=tmp_path / "storage",
            assets_dir=assets_dir,
            planets=MagicMock(),
            turn_load=MagicMock(),
            game_service=MagicMock(),
            storage=MagicMock(),
            dry_run=False,
            workers=1,
        )

    assert report.aborted is True
    assert report.abort_message == "simulated fatal abort"
    assert report.written_assets == [str(assets_dir / "prior_weights_standard.yaml")]
    reloaded = load_prior_weights_asset(assets_dir / "prior_weights_standard.yaml")
    assert 100001 in reloaded.contributing_game_ids
    assert 100002 in reloaded.contributing_game_ids
    assert reloaded.hulls["before_ship_limit"]["global"]["battleship"][13] >= 1


def test_run_prior_miner_does_not_mark_aborted_when_all_patterns_complete(tmp_path: Path):
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text("version: 1\npatterns: []\n", encoding="utf-8")
    pattern = _standard_pattern()
    config = PriorMiningPatternConfig(version=1, patterns=(pattern,))

    with (
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.load_prior_mining_patterns",
            return_value=config,
        ),
        patch(
            "api.analytics.military_score_inference.prior_mining.runner._mine_pattern",
            return_value=_discovery_result(pattern),
        ),
    ):
        report = run_prior_miner(
            patterns_path=patterns_path,
            storage_root=tmp_path / "storage",
            assets_dir=tmp_path / "assets",
            planets=MagicMock(),
            turn_load=MagicMock(),
            game_service=MagicMock(),
            storage=MagicMock(),
            dry_run=True,
            workers=1,
        )

    assert report.aborted is False
    assert report.abort_message is None


def test_mine_pattern_prefetches_next_game_before_processing_current():
    pattern = _standard_pattern(max_games=2)
    state = _empty_standard_category_state()
    report = PriorMiningReport(dry_run=True)
    events: list[tuple[str, int]] = []
    info = MagicMock()
    info.settings.nominefields = False
    game_service = MagicMock()
    game_service.get_game_info.return_value = info

    def fake_submit(game_id: int) -> Future:
        events.append(("submit", game_id))
        return _completed_future(PrepareGameResult(game_id=game_id, outcome="ready"))

    mock_prefetcher = MagicMock()
    mock_prefetcher.submit.side_effect = fake_submit
    mock_extraction_pool = MagicMock()

    def fake_extract(*, game_id: int, **kwargs):
        del kwargs
        events.append(("extract", game_id))
        return ExtractionRunSummary(units_ok=1)

    with (
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.iter_accepted_games_for_pattern",
            return_value=iter([101, 102]),
        ),
        patch(_PREFETCH_PREPARE) as mock_prepare_cls,
        patch(_PREFETCH_POOL) as mock_pool_cls,
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.run_extractions_for_game",
            side_effect=fake_extract,
        ),
        patch(
            "api.analytics.military_score_inference.prior_mining.mine_stock_pipeline.run_mine_stock_extractions_for_game",
            return_value=MineStockRunSummary(),
        ),
    ):
        mock_prepare_cls.return_value.__enter__.return_value = mock_prefetcher
        mock_pool_cls.return_value.__enter__.return_value = mock_extraction_pool
        _mine_pattern(
            pattern=pattern,
            state=state,
            planets=MagicMock(),
            turn_load=MagicMock(),
            game_service=game_service,
            storage_root=Path(".data"),
            report=report,
            debug=False,
            workers=8,
            loadall_params=None,
        )

    assert events.index(("submit", 102)) < events.index(("extract", 101))


def test_prefetch_and_process_games_submits_next_before_processing_current():
    events: list[tuple[str, int]] = []
    scheduled: list[int] = []

    def fake_submit(game_id: int) -> Future:
        events.append(("submit", game_id))
        return _completed_future(PrepareGameResult(game_id=game_id, outcome="ready"))

    def on_scheduled(game_id: int) -> None:
        scheduled.append(game_id)

    def process_prepared(prepared: PrepareGameResult, extraction_pool: object) -> None:
        del extraction_pool
        events.append(("process", prepared.game_id))

    mock_prefetcher = MagicMock()
    mock_prefetcher.submit.side_effect = fake_submit
    mock_extraction_pool = MagicMock()

    with (
        patch(_PREFETCH_PREPARE) as mock_prepare_cls,
        patch(_PREFETCH_POOL) as mock_pool_cls,
    ):
        mock_prepare_cls.return_value.__enter__.return_value = mock_prefetcher
        mock_pool_cls.return_value.__enter__.return_value = mock_extraction_pool
        prefetch_and_process_games(
            game_ids=[101, 102],
            storage_root=Path(".data"),
            loadall_params=None,
            workers=1,
            on_scheduled=on_scheduled,
            process_prepared=process_prepared,
        )

    assert scheduled == [101, 102]
    assert events == [
        ("submit", 101),
        ("submit", 102),
        ("process", 101),
        ("process", 102),
    ]


def test_replay_mine_stock_writes_sibling_asset_without_touching_prior_weights(tmp_path: Path):
    from api.analytics.military_score_inference.prior_mining.extraction_pool import (
        MineStockRunSummary,
    )
    from api.analytics.military_score_inference.prior_mining.mine_stock import MineStockSample
    from api.analytics.military_score_inference.prior_mining.patterns import (
        PriorMiningPatternConfig,
    )

    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(
        "version: 1\npatterns:\n"
        "  - id: standard-v1\n    game_category: standard\n"
        "    max_games: 100\n    min_difficulty: 1.0\n    earliest_date: '2024-01-01'\n",
        encoding="utf-8",
    )
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    prior_path = assets_dir / "prior_weights_standard.yaml"
    prior_text = HAND_SEEDED_STANDARD_PRIOR_PATH.read_text(encoding="utf-8")
    prior_path.write_text(prior_text + "\ncontributingGameIds:\n  - 101\n", encoding="utf-8")
    prior_before = prior_path.read_text(encoding="utf-8")

    def fake_mine_stock(*, accumulation, **kwargs):
        del kwargs
        accumulation.add_sample(
            MineStockSample(
                race_id=1,
                host_turn=40,
                total_units=400,
                field_count=2,
                per_field_units=(300, 100),
                web_total_units=0,
                web_field_count=0,
                web_per_field_units=(),
                normal_total_units=400,
                normal_field_count=2,
                normal_per_field_units=(300, 100),
                infoturn_mismatches=0,
            )
        )
        return MineStockRunSummary(units_ok=1, units_enqueued=1)

    info = MagicMock()
    info.settings.nominefields = False
    game_service = MagicMock()
    game_service.get_game_info.return_value = info

    mock_prefetcher = MagicMock()
    mock_prefetcher.submit.side_effect = lambda game_id: _completed_future(
        PrepareGameResult(game_id=game_id, outcome="ready")
    )
    mock_extraction_pool = MagicMock()
    pattern = _standard_pattern()
    config = PriorMiningPatternConfig(version=1, patterns=(pattern,))

    with (
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.load_prior_mining_patterns",
            return_value=config,
        ),
        patch(_PREFETCH_PREPARE) as mock_prepare_cls,
        patch(_PREFETCH_POOL) as mock_pool_cls,
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.run_extractions_for_game",
            side_effect=AssertionError("replay must not mine build priors"),
        ),
        patch(
            "api.analytics.military_score_inference.prior_mining.mine_stock_pipeline.run_mine_stock_extractions_for_game",
            side_effect=fake_mine_stock,
        ),
    ):
        mock_prepare_cls.return_value.__enter__.return_value = mock_prefetcher
        mock_pool_cls.return_value.__enter__.return_value = mock_extraction_pool
        report = run_prior_miner(
            patterns_path=patterns_path,
            storage_root=tmp_path / "storage",
            assets_dir=assets_dir,
            planets=MagicMock(),
            turn_load=MagicMock(),
            game_service=game_service,
            storage=MagicMock(),
            dry_run=False,
            workers=1,
            replay_mine_stock=True,
        )

    assert report.replay_mine_stock is True
    assert report.mine_stock_games_added == [101]
    assert report.mine_stock_samples == 1
    mine_stock_path = assets_dir / "mine_stock_standard.yaml"
    assert mine_stock_path.is_file()
    assert str(mine_stock_path) in report.written_assets
    assert prior_path.read_text(encoding="utf-8") == prior_before
    reloaded = load_prior_weights_asset(prior_path, require_complete_aggregates=False)
    assert 101 in reloaded.contributing_game_ids


def test_process_prepared_mine_stock_game_records_incomplete_on_skip_set():
    mine_stock = MineStockCategoryState(asset=create_empty_mine_stock_asset(GameCategory.STANDARD))
    report = PriorMiningReport(dry_run=True)
    prepared = PrepareGameResult(
        game_id=7,
        outcome="skipped_incomplete",
        incomplete_gaps=(
            IncompleteGapDetail(perspective=1, username="p1", missing_turns=(10, 11)),
        ),
    )

    result = process_prepared_mine_stock_game(
        prepared=prepared,
        game_service=MagicMock(),
        turn_load=MagicMock(),
        storage_root=Path(".data"),
        workers=1,
        mine_stock=mine_stock,
        report=report,
        extraction_pool=MagicMock(),
    )

    assert result is None
    assert 7 in mine_stock.game_ids
    assert report.games_skipped_incomplete_loadall == 1
    assert report.incomplete_loadall_details[0].game_id == 7


def test_process_prepared_mine_stock_game_skips_nominefields_without_extract():
    mine_stock = MineStockCategoryState(asset=create_empty_mine_stock_asset(GameCategory.STANDARD))
    report = PriorMiningReport(dry_run=True)
    info = MagicMock()
    info.settings.nominefields = True
    game_service = MagicMock()
    game_service.get_game_info.return_value = info

    with patch(
        "api.analytics.military_score_inference.prior_mining.mine_stock_pipeline.run_mine_stock_extractions_for_game",
        side_effect=AssertionError("nominefields must skip extract"),
    ):
        result = process_prepared_mine_stock_game(
            prepared=PrepareGameResult(game_id=9, outcome="ready"),
            game_service=game_service,
            turn_load=MagicMock(),
            storage_root=Path(".data"),
            workers=1,
            mine_stock=mine_stock,
            report=report,
            extraction_pool=MagicMock(),
        )

    assert result is info
    assert 9 in mine_stock.game_ids
    assert report.mine_stock_nominefields_skips == 1
