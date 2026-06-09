"""Tests for accelerated-start scoreboard reconstruction."""

import json
from pathlib import Path

import pytest
from api.analytics.military_score_inference.accelerated_start import (
    ACCEL_WINDOW_SEGMENT_ID,
    HOMEBASE_STARTING_FREIGHTERS,
    REPORTED_HOST_TURN_SEGMENT_ID,
    SCOREBOARD_MILITARY_PARTITION_SLACK_2X,
    accelerated_inference_segments,
    accelerated_window_military_change,
    accelerated_window_military_delta_2x,
    cumulative_military_delta_2x,
    effective_prior_score_row,
    homeworld_baseline_military_2x,
    infer_accelerated_window_ship_builds,
    is_first_reliable_scoreboard_turn,
    is_unreliable_accelerated_scoreboard_turn,
    observation_deltas_from_score,
    reported_host_military_delta_2x,
    starting_scoreboard_snapshot,
    synthetic_scoreboard_before_reported_deltas,
)
from api.analytics.military_score_inference.analytic import (
    build_inference_observation,
    infer_military_score_build,
    prior_turn_score_data_available,
    run_inference_with_artifacts,
)
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
)
from api.serialization.game import game_info_from_json
from api.serialization.turn import turn_info_from_json

from tests.inference_corpus.fixtures import load_turn_fixture
from tests.inference_corpus.manifest import load_manifest, resolve_player_id

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
    assert homeworld_baseline_military_2x(settings) == 4220
    assert baseline.freighters == 1
    assert baseline.capitalships == 0
    assert baseline.starbases == 1


def test_scoreboard_partition_slack_constant():
    assert SCOREBOARD_MILITARY_PARTITION_SLACK_2X == 1


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
def test_first_reliable_turn_observation_uses_reported_host_turn_deltas():
    turn = _load_store_turn(3)
    score = next(s for s in turn.scores if s.ownerid == 1)
    assert is_first_reliable_scoreboard_turn(3, turn.settings)
    military_delta_2x, warship_delta, freighter_delta, _priority, _source = (
        observation_deltas_from_score(score, turn)
    )
    assert military_delta_2x == 2 * score.militarychange
    assert warship_delta == score.shipchange
    assert freighter_delta == score.freighterchange
    observation = build_inference_observation(score, turn)
    assert observation.military_delta_2x == military_delta_2x
    assert observation.freighter_delta == freighter_delta


@pytest.mark.skipif(not DATA_ROOT.joinpath("3.json").is_file(), reason="local store only")
def test_accelerated_window_residual_matches_cumulative_minus_reported_delta():
    turn = _load_store_turn(3)
    score = next(s for s in turn.scores if s.ownerid == 1)
    baseline = starting_scoreboard_snapshot(turn.settings)
    cumulative_2x = cumulative_military_delta_2x(score, turn.settings)
    reported_2x = reported_host_military_delta_2x(score)
    assert cumulative_2x == 2 * (score.militaryscore - baseline.militaryscore)
    assert accelerated_window_military_delta_2x(score, turn) == cumulative_2x - reported_2x
    assert accelerated_window_military_change(score, turn) == (
        score.militaryscore - baseline.militaryscore - score.militarychange
    )
    segments = accelerated_inference_segments(score, turn)
    assert segments is not None
    assert segments[-1].segment_id == REPORTED_HOST_TURN_SEGMENT_ID
    assert segments[-1].military_delta_2x == reported_2x
    assert segments[0].segment_id == ACCEL_WINDOW_SEGMENT_ID
    assert segments[0].military_delta_2x == cumulative_2x - reported_2x
    assert segments[0].military_delta_2x == 110
    assert segments[0].freighter_delta == 1


@pytest.mark.skipif(not DATA_ROOT.joinpath("4.json").is_file(), reason="local store only")
def test_turn4_uses_scoreboard_delta_fields():
    turn = _load_store_turn(4)
    score = next(s for s in turn.scores if s.ownerid == 1)
    military_delta_2x, warship_delta, freighter_delta, _priority, _source = (
        observation_deltas_from_score(score, turn)
    )
    assert military_delta_2x == 2 * score.militarychange
    assert warship_delta == score.shipchange
    assert freighter_delta == score.freighterchange


def test_fixture_turn3_observation_uses_reported_host_turn_delta():
    _, cases = load_manifest()
    turn = load_turn_fixture(cases[0].score_turn_path)
    player_id = resolve_player_id(cases[0])
    score = next(s for s in turn.scores if s.ownerid == player_id)
    assert turn.settings.acceleratedturns == 3
    observation = build_inference_observation(score, turn)
    assert observation.military_delta_2x == 2 * score.militarychange
    assert observation.warship_delta == score.shipchange
    assert observation.freighter_delta == score.freighterchange


@pytest.mark.skipif(not DATA_ROOT.joinpath("3.json").is_file(), reason="local store only")
def test_unreliable_turn2_backfills_host_turn1_when_turn3_stored():
    turn_two = _load_store_turn(2)
    score = next(s for s in turn_two.scores if s.ownerid == 1)

    without_loader, _, _ = run_inference_with_artifacts(score, turn_two)
    assert without_loader["status"] == STATUS_NO_PRIOR_TURN

    def load_scoreboard_turn(turn_number: int):
        if turn_number != 3:
            return None
        return _load_store_turn(3)

    with_loader, observation, _ = run_inference_with_artifacts(
        score,
        turn_two,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    assert with_loader["status"] == "exact"
    assert with_loader["solutionCount"] >= 1
    assert with_loader["diagnostics"]["accelerated_backfill"] is True
    assert with_loader["diagnostics"]["accelerated_backfill_host_turn"] == 1
    assert with_loader["diagnostics"]["accelerated_backfill_source_turn"] == 3
    assert observation.military_delta_2x == 110
    action_labels = [
        action["label"] for solution in with_loader["solutions"] for action in solution["actions"]
    ]
    assert any("Planet defense" in label for label in action_labels)


@pytest.mark.skipif(not DATA_ROOT.joinpath("3.json").is_file(), reason="local store only")
def test_unreliable_turn2_fails_when_turn3_not_stored():
    turn_two = _load_store_turn(2)
    score = next(s for s in turn_two.scores if s.ownerid == 1)
    payload, _, _ = run_inference_with_artifacts(
        score,
        turn_two,
        load_scoreboard_turn=lambda _turn_number: None,
    )
    assert payload["status"] == STATUS_NO_PRIOR_TURN
    assert payload["diagnostics"]["reason"] == "accelerated_backfill_unavailable"


def test_corpus_case_still_infers_exact_with_accelerated_adjustment():
    _, cases = load_manifest()
    case = cases[0]
    turn = load_turn_fixture(case.score_turn_path)
    player_id = resolve_player_id(case)
    score = next(s for s in turn.scores if s.ownerid == player_id)
    result = infer_military_score_build(score, turn)
    assert result["status"] == "exact"
    assert result["solutionCount"] >= 1


def test_p2_turn3_accel_segment_includes_freighter_only_window():
    turn = load_turn_fixture("628580/1/turns/3.json")
    score = next(s for s in turn.scores if s.ownerid == 2)
    segments = accelerated_inference_segments(score, turn)
    assert segments is not None
    assert segments[0].segment_id == ACCEL_WINDOW_SEGMENT_ID
    assert segments[0].military_delta_2x == 0
    assert segments[0].freighter_delta == 1
    assert segments[-1].freighter_delta == 1


def test_p2_unreliable_turn2_backfills_host_turn1_freighter_only():
    turn_two = load_turn_fixture("628580/1/turns/2.json")
    score = next(s for s in turn_two.scores if s.ownerid == 2)

    without_loader, _, _ = run_inference_with_artifacts(score, turn_two)
    assert without_loader["status"] == STATUS_NO_PRIOR_TURN

    def load_scoreboard_turn(turn_number: int):
        if turn_number != 3:
            return None
        return load_turn_fixture("628580/1/turns/3.json")

    with_loader, observation, _ = run_inference_with_artifacts(
        score,
        turn_two,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    assert with_loader["status"] == "exact"
    assert with_loader["solutionCount"] >= 1
    assert observation.military_delta_2x == 0
    assert observation.freighter_delta == 1
    assert with_loader["diagnostics"]["accelerated_backfill"] is True
    assert with_loader["diagnostics"]["accelerated_backfill_host_turn"] == 1
