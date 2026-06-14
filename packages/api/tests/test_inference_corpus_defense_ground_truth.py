"""Tests for three-component planet/starbase defense ground truth (#73)."""

import json
from dataclasses import replace
from unittest.mock import patch

from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.analytics.military_score_inference.ship_inventory import (
    planet_defense_inventory_delta,
    starbase_defense_inventory_delta,
)
from api.models.starbase import Starbase
from api.serialization.turn import turn_info_from_json

from tests.inference_corpus.case_helpers import score_for_player
from tests.inference_corpus.complexity import classify_complexity, merge_turn_inventories
from tests.inference_corpus.fixtures import FIXTURES_ROOT, load_turn_fixture
from tests.inference_corpus.ground_truth import (
    GroundTruthExtraction,
    defense_aggregate_counts_negative,
    extract_ground_truth_v1,
)
from tests.inference_corpus.manifest import load_manifest
from tests.inference_corpus.models import CaseOutcome
from tests.inference_corpus.run import run_manifest_case


def _settings_defaults() -> dict:
    return json.loads((FIXTURES_ROOT / "628580/info.json").read_text())["settings"]


def _lynch_turn_pair():
    prior_turn = load_turn_fixture("628580/1/turns/1.json")
    score_turn = load_turn_fixture("628580/1/turns/2.json")
    return prior_turn, score_turn


def test_planet_defense_delta_lynch_builtdefense_rows():
    prior_turn, score_turn = _lynch_turn_pair()
    lynch_prior = next(planet for planet in prior_turn.planets if planet.id == 272)
    lynch_score = next(planet for planet in score_turn.planets if planet.id == 272)

    assert lynch_prior.builtdefense == 10
    assert lynch_prior.defense == 30
    assert lynch_score.builtdefense == 0
    assert lynch_score.defense == 30
    assert planet_defense_inventory_delta(prior_turn, score_turn, player_id=1) == 10


def test_extract_ground_truth_host1_includes_freighter_and_planet_defense():
    prior_turn, score_turn = _lynch_turn_pair()
    score = score_for_player(score_turn.scores, 1, "628580-p1-host1")
    merged = merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=(),
        other_score_turns=(),
    )
    complexity, _ = classify_complexity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=1,
        score=score,
        merged=merged,
    )
    extraction = extract_ground_truth_v1(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=1,
        score=score,
        complexity=complexity,
    )

    assert extraction.available is True
    assert extraction.ground_truth == (
        (GENERIC_FREIGHTER_COMBO_ID, 1),
        ("planet_defense_posts_added_total", 10),
    )
    assert defense_aggregate_counts_negative(extraction.ground_truth) is False


def test_planet_defense_capture_gain_and_loss():
    settings = _settings_defaults()
    base = json.loads((FIXTURES_ROOT / "628580/1/turns/2.json").read_text())
    prior_data = json.loads(json.dumps(base))
    score_data = json.loads(json.dumps(base))
    prior_turn = turn_info_from_json(prior_data, settings_defaults=settings)
    score_turn = turn_info_from_json(score_data, settings_defaults=settings)

    captured = replace(
        score_turn.planets[0],
        id=999,
        ownerid=1,
        defense=7,
        builtdefense=0,
    )
    score_turn = replace(score_turn, planets=(*score_turn.planets, captured))
    assert planet_defense_inventory_delta(prior_turn, score_turn, player_id=1) == 7

    lost = replace(
        prior_turn.planets[0],
        id=888,
        ownerid=1,
        defense=5,
        builtdefense=0,
    )
    prior_with_loss = replace(prior_turn, planets=(*prior_turn.planets, lost))
    assert planet_defense_inventory_delta(prior_with_loss, score_turn, player_id=1) == 2


def test_starbase_defense_three_component_net():
    settings = _settings_defaults()
    base = json.loads((FIXTURES_ROOT / "628580/1/turns/2.json").read_text())
    prior_data = json.loads(json.dumps(base))
    score_data = json.loads(json.dumps(base))
    prior_turn = turn_info_from_json(prior_data, settings_defaults=settings)
    score_turn = turn_info_from_json(score_data, settings_defaults=settings)

    planet = score_turn.planets[0]
    prior_starbase = Starbase(
        id=1,
        defense=4,
        builtdefense=3,
        damage=0,
        enginetechlevel=0,
        hulltechlevel=0,
        beamtechlevel=0,
        torptechlevel=0,
        hulltechup=0,
        enginetechup=0,
        beamtechup=0,
        torptechup=0,
        fighters=0,
        builtfighters=0,
        shipmission=0,
        mission=0,
        mission1target=0,
        planetid=planet.id,
        raceid=1,
        targetshipid=0,
        buildbeamid=0,
        buildengineid=0,
        buildtorpedoid=0,
        buildhullid=0,
        buildbeamcount=0,
        buildtorpcount=0,
        isbuilding=False,
        starbasetype=0,
        infoturn=0,
        readystatus=0,
    )
    prior_turn = replace(prior_turn, starbases=(prior_starbase,))
    assert starbase_defense_inventory_delta(prior_turn, score_turn, player_id=1) == 3


def test_negative_defense_gt_detected_in_multiset():
    assert defense_aggregate_counts_negative((("planet_defense_posts_added_total", -1),)) is True
    assert defense_aggregate_counts_negative((("planet_defense_posts_added_total", 10),)) is False


def test_harness_skips_coverage_and_ranking_for_negative_defense_gt():
    _, cases = load_manifest()
    host1 = next(case for case in cases if case.id == "628580-p1-host1")
    negative_gt = (("planet_defense_posts_added_total", -5),)

    with patch(
        "tests.inference_corpus.run.extract_ground_truth_v1",
        return_value=GroundTruthExtraction(available=True, ground_truth=negative_gt),
    ):
        result = run_manifest_case(host1)

    assert result.outcome == CaseOutcome.SKIPPED_PENDING_SOLVER
    assert result.skip_reason == "negative_defense_gt_pending_solver"
    assert result.ground_truth_available is True


def test_manifest_host1_passes_ranking_with_require_top_k():
    _, cases = load_manifest()
    host1 = next(case for case in cases if case.id == "628580-p1-host1")
    assert host1.require_top_k is True
    result = run_manifest_case(host1)
    assert result.outcome == CaseOutcome.PASSED, result.failure_message or result.skip_reason
