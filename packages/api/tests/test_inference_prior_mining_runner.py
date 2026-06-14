"""Tests for prior mining runner resilience and checkpoint flush."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

from api.analytics.military_score_inference.prior_mining.discovery import PatternDiscoveryResult
from api.analytics.military_score_inference.prior_mining.extraction_pool import ExtractionRunSummary
from api.analytics.military_score_inference.prior_mining.merge import load_prior_weights_asset
from api.analytics.military_score_inference.prior_mining.observations import ShipBuildObservation
from api.analytics.military_score_inference.prior_mining.patterns import (
    PriorMiningPattern,
    PriorMiningPatternConfig,
)
from api.analytics.military_score_inference.prior_mining.prepare_game import PrepareGameResult
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
    state = CategoryMiningState(asset=create_empty_prior_weights_asset(GameCategory.STANDARD))
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

    with (
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.iter_accepted_games_for_pattern",
            return_value=iter([656637, 656638]),
        ),
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.GamePreparePrefetcher"
        ) as mock_prepare_cls,
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.ExtractionProcessPool"
        ) as mock_pool_cls,
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.run_extractions_for_game",
            return_value=ExtractionRunSummary(units_ok=1),
        ),
    ):
        mock_prepare_cls.return_value.__enter__.return_value = mock_prefetcher
        mock_pool_cls.return_value.__enter__.return_value = mock_extraction_pool
        result = _mine_pattern(
            pattern=pattern,
            state=state,
            planets=MagicMock(),
            turn_load=MagicMock(),
            game_service=MagicMock(),
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
    assert reloaded.hulls["before_ship_limit"]["global"][13] >= 1


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
    state = CategoryMiningState(asset=create_empty_prior_weights_asset(GameCategory.STANDARD))
    report = PriorMiningReport(dry_run=True)
    events: list[tuple[str, int]] = []

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
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.GamePreparePrefetcher"
        ) as mock_prepare_cls,
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.ExtractionProcessPool"
        ) as mock_pool_cls,
        patch(
            "api.analytics.military_score_inference.prior_mining.runner.run_extractions_for_game",
            side_effect=fake_extract,
        ),
    ):
        mock_prepare_cls.return_value.__enter__.return_value = mock_prefetcher
        mock_pool_cls.return_value.__enter__.return_value = mock_extraction_pool
        _mine_pattern(
            pattern=pattern,
            state=state,
            planets=MagicMock(),
            turn_load=MagicMock(),
            game_service=MagicMock(),
            storage_root=Path(".data"),
            report=report,
            debug=False,
            workers=8,
            loadall_params=None,
        )

    assert events.index(("submit", 102)) < events.index(("extract", 101))
