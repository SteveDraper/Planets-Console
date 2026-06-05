"""Tests for inference corpus complexity classification."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.serialization.turn import turn_info_from_json

from tests.inference_corpus.complexity import (
    classify_complexity,
    merge_turn_inventories,
    parse_max_complexity,
)
from tests.inference_corpus.manifest import FIXTURES_ROOT

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        return turn_info_from_json(json.load(handle))


@pytest.fixture
def corpus_turn_pair():
    prior_path = FIXTURES_ROOT / "628580/1/turns/2.json"
    score_path = FIXTURES_ROOT / "628580/1/turns/3.json"
    settings_defaults = json.loads((FIXTURES_ROOT / "628580/info.json").read_text())["settings"]
    with open(prior_path) as handle:
        prior_turn = turn_info_from_json(json.load(handle), settings_defaults=settings_defaults)
    with open(score_path) as handle:
        score_turn = turn_info_from_json(json.load(handle), settings_defaults=settings_defaults)
    return prior_turn, score_turn


def test_parse_max_complexity_accepts_names_and_ordinals():
    assert parse_max_complexity("minimal") == "minimal"
    assert parse_max_complexity("2") == "heavy"
    assert parse_max_complexity("HEAVY") == "heavy"


def test_parse_max_complexity_rejects_invalid_values():
    with pytest.raises(ValueError, match="invalid max complexity"):
        parse_max_complexity("extreme")


def test_classify_seed_fixture_case_is_minimal(corpus_turn_pair):
    prior_turn, score_turn = corpus_turn_pair
    player_id = 1
    score = next(row for row in score_turn.scores if row.ownerid == player_id)
    merged = merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=(),
        other_score_turns=(),
    )

    complexity, reasons = classify_complexity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        merged=merged,
    )

    assert complexity == "routine"
    assert any("aggregate_load_units=" in reason for reason in reasons)


def test_classify_marks_adjunct_when_owned_ship_count_decreases(sample_turn):
    player_id = sample_turn.scores[0].ownerid
    owned = next(
        ship for ship in sample_turn.ships if ship.ownerid == player_id and ship.turnkilled == 0
    )
    prior_turn = replace(sample_turn, settings=replace(sample_turn.settings, turn=10))
    score_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=11),
        ships=[ship for ship in sample_turn.ships if ship.id != owned.id],
    )
    score = replace(sample_turn.scores[0], ownerid=player_id, militarychange=0)
    merged = merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=(),
        other_score_turns=(),
    )

    complexity, reasons = classify_complexity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        merged=merged,
    )

    assert complexity == "adjunct"
    assert "net_ship_count_decrease" in reasons


def test_classify_marks_heavy_for_many_new_ships(sample_turn):
    player_id = sample_turn.scores[0].ownerid
    template = next(
        ship for ship in sample_turn.ships if ship.ownerid == player_id and ship.turnkilled == 0
    )
    prior_turn = replace(sample_turn, settings=replace(sample_turn.settings, turn=10), ships=[])
    new_ships = [replace(template, id=1000 + index, turn=11, turnkilled=0) for index in range(3)]
    score_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=11),
        ships=new_ships,
    )
    score = replace(sample_turn.scores[0], ownerid=player_id, militarychange=100)
    merged = merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=(),
        other_score_turns=(),
    )

    complexity, reasons = classify_complexity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        merged=merged,
    )

    assert complexity == "heavy"
    assert any(reason.startswith("new_ships=") for reason in reasons)
