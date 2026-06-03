"""Tests for accelerated-start scoreboard reconstruction."""

import json
from pathlib import Path

import pytest
from api.analytics.military_score_inference.accelerated_start import (
    HOMEBASE_STARTING_FREIGHTERS,
    effective_prior_score_row,
    infer_accelerated_window_ship_builds,
    is_first_reliable_scoreboard_turn,
    is_unreliable_accelerated_scoreboard_turn,
    observation_deltas_from_score,
    starting_scoreboard_snapshot,
    synthetic_scoreboard_before_reported_deltas,
)
from api.analytics.military_score_inference.analytic import (
    build_inference_observation,
    prior_turn_score_data_available,
)
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = REPO_ROOT / ".data" / "games" / "628580" / "1" / "turns"
GAME_INFO_PATH = REPO_ROOT / ".data" / "games" / "628580" / "info.json"


def _game_settings_from_sample():
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        return game_info_from_json(json.load(handle)).settings


def _load_store_turn(turn_number: int):
    with open(GAME_INFO_PATH) as info_handle:
        settings_defaults = json.load(info_handle)["settings"]
    with open(DATA_ROOT / f"{turn_number}.json") as handle:
        return turn_info_from_json(json.load(handle), settings_defaults=settings_defaults)


def test_sample_game_has_three_accelerated_turns():
    settings = _game_settings_from_sample()
    assert settings.acceleratedturns == 3


def test_unreliable_scoreboard_turns_for_accelerated_start():
    game_settings = _game_settings_from_sample()
    assert is_unreliable_accelerated_scoreboard_turn(1, game_settings)
    assert is_unreliable_accelerated_scoreboard_turn(2, game_settings)
    assert not is_unreliable_accelerated_scoreboard_turn(3, game_settings)


@pytest.mark.skipif(not DATA_ROOT.joinpath("2.json").is_file(), reason="local store only")
def test_prior_turn_unavailable_during_accelerated_window():
    turn = _load_store_turn(2)
    assert not prior_turn_score_data_available(turn)
    turn_three = _load_store_turn(3)
    assert prior_turn_score_data_available(turn_three)


def test_starting_baseline_uses_twenty_fighters_and_one_freighter():
    settings = _game_settings_from_sample()
    baseline = starting_scoreboard_snapshot(settings)
    assert baseline.militaryscore == 2110
    assert baseline.freighters == 1
    assert baseline.capitalships == 0
    assert baseline.starbases == 1


@pytest.mark.skipif(not DATA_ROOT.joinpath("3.json").is_file(), reason="local store only")
def test_turn3_scoreboard_infers_accel_freighter_and_host2_warship():
    """Freighters 2 (+0) and Military 1 (+1) on first reliable turn (N=3)."""
    turn = _load_store_turn(3)
    score = next(s for s in turn.scores if s.ownerid == 1)
    builds = infer_accelerated_window_ship_builds(score, turn)
    assert builds is not None
    assert score.freighters == 2
    assert score.freighterchange == 0
    assert score.capitalships == 1
    assert score.shipchange == 1
    assert builds.turn_one_baseline.freighters == HOMEBASE_STARTING_FREIGHTERS
    assert builds.inferred_prior_to_reported_host_turn.freighters == 2
    assert builds.inferred_prior_to_reported_host_turn.capitalships == 0
    assert builds.freighters_built_before_reported_host_turn == 1
    assert builds.warships_built_before_reported_host_turn == 0
    assert builds.freighters_built_on_reported_host_turn == 0
    assert builds.warships_built_on_reported_host_turn == 1


@pytest.mark.skipif(not DATA_ROOT.joinpath("3.json").is_file(), reason="local store only")
def test_synthetic_prior_from_turn3_matches_subtracted_totals():
    turn = _load_store_turn(3)
    score = next(s for s in turn.scores if s.ownerid == 1)
    snapshot = synthetic_scoreboard_before_reported_deltas(score)
    assert snapshot.militaryscore == 6440 - 4275
    assert snapshot.capitalships == 0
    prior_row = effective_prior_score_row(score_at_reliable_turn=score, turn_at_reliable_turn=turn)
    assert prior_row.militaryscore == snapshot.militaryscore


@pytest.mark.skipif(not DATA_ROOT.joinpath("3.json").is_file(), reason="local store only")
def test_first_reliable_turn_observation_uses_starting_baseline():
    turn = _load_store_turn(3)
    score = next(s for s in turn.scores if s.ownerid == 1)
    assert is_first_reliable_scoreboard_turn(3, turn.settings)
    military_delta_2x, warship_delta, freighter_delta, _priority = observation_deltas_from_score(
        score, turn
    )
    baseline = starting_scoreboard_snapshot(turn.settings)
    assert military_delta_2x == 2 * (score.militaryscore - baseline.militaryscore)
    assert warship_delta == 1
    assert freighter_delta == score.freighterchange
    observation = build_inference_observation(score, turn)
    assert observation.military_delta_2x == military_delta_2x
    assert observation.freighter_delta == freighter_delta


@pytest.mark.skipif(not DATA_ROOT.joinpath("4.json").is_file(), reason="local store only")
def test_turn4_uses_scoreboard_delta_fields():
    turn = _load_store_turn(4)
    score = next(s for s in turn.scores if s.ownerid == 1)
    military_delta_2x, warship_delta, freighter_delta, _priority = observation_deltas_from_score(
        score, turn
    )
    assert military_delta_2x == 2 * score.militarychange
    assert warship_delta == score.shipchange
    assert freighter_delta == score.freighterchange
