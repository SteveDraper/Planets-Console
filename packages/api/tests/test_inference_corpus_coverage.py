"""Tests for inference corpus ground truth extraction and catalog coverage (#64)."""

from unittest.mock import patch

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_action_catalog_from_turn,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.models import CandidateAction

from tests.inference_corpus.case_helpers import score_for_player
from tests.inference_corpus.catalog_coverage import (
    COVERAGE_REASON_ACTION_NOT_IN_CATALOG,
    COVERAGE_REASON_COMBO_NOT_IN_CATALOG,
    COVERAGE_REASON_COUNT_ABOVE_UPPER_BOUND,
    COVERAGE_REASON_GROUND_TRUTH_UNAVAILABLE,
    evaluate_catalog_coverage,
    resolve_coverage_for_case,
)
from tests.inference_corpus.fixtures import load_turn_fixture
from tests.inference_corpus.ground_truth import GroundTruthExtraction, extract_ground_truth_v1
from tests.inference_corpus.manifest import FIXTURES_ROOT, load_manifest, resolve_player_id
from tests.inference_corpus.models import CaseOutcome
from tests.inference_corpus.run import run_manifest_case


def test_evaluate_catalog_coverage_accepts_empty_ground_truth():
    catalog = ActionCatalog(
        aggregate_actions=(),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    result = evaluate_catalog_coverage((), catalog)
    assert result.in_search_space is True
    assert result.coverage_reason is None


def test_evaluate_catalog_coverage_unknown_action():
    catalog = ActionCatalog(
        aggregate_actions=(
            CandidateAction(
                id="ship_fighters_added_total",
                label="fighters",
                score_delta_2x=125,
                warship_delta=0,
                freighter_delta=0,
                build_slot_usage=0,
                upper_bound=10,
            ),
        ),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    result = evaluate_catalog_coverage((("missing_action", 1),), catalog)
    assert result.in_search_space is False
    assert result.coverage_reason == COVERAGE_REASON_ACTION_NOT_IN_CATALOG


def test_evaluate_catalog_coverage_combo_not_in_catalog():
    catalog = ActionCatalog(
        aggregate_actions=(),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    result = evaluate_catalog_coverage((("build_99_torpedoes", 1),), catalog)
    assert result.in_search_space is False
    assert result.coverage_reason == COVERAGE_REASON_COMBO_NOT_IN_CATALOG


def test_evaluate_catalog_coverage_count_above_upper_bound():
    catalog = ActionCatalog(
        aggregate_actions=(
            CandidateAction(
                id="ship_fighters_added_total",
                label="fighters",
                score_delta_2x=125,
                warship_delta=0,
                freighter_delta=0,
                build_slot_usage=0,
                upper_bound=2,
            ),
        ),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    result = evaluate_catalog_coverage((("ship_fighters_added_total", 5),), catalog)
    assert result.in_search_space is False
    assert result.coverage_reason == COVERAGE_REASON_COUNT_ABOVE_UPPER_BOUND


def test_resolve_coverage_skips_when_ground_truth_unavailable():
    catalog = ActionCatalog(
        aggregate_actions=(),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    extraction = GroundTruthExtraction(available=False, unavailable_reason="residual_unexplained")
    result = resolve_coverage_for_case(
        extraction=extraction,
        ground_truth=(),
        catalog=catalog,
        complexity_reasons=(),
    )
    assert result is None


def test_seed_host2_strict_ground_truth_unavailable():
    _, cases = load_manifest()
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    prior = load_turn_fixture(host2.prior_turn_path, fixtures_root=FIXTURES_ROOT)
    score_turn = load_turn_fixture(host2.score_turn_path, fixtures_root=FIXTURES_ROOT)
    player_id = resolve_player_id(host2, fixtures_root=FIXTURES_ROOT)
    score = score_for_player(score_turn.scores, player_id, host2.id)
    extraction = extract_ground_truth_v1(
        prior_turn=prior,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        complexity="minimal",
    )
    assert extraction.available is False
    assert extraction.unavailable_reason == "residual_unexplained"


def test_host51_manifest_case_coverage_passes_tier1():
    _, cases = load_manifest()
    host51 = next(case for case in cases if case.id == "628580-p1-host51")
    result = run_manifest_case(host51)
    assert result.outcome == CaseOutcome.PASSED
    assert result.ground_truth_available is True
    assert result.coverage_reason is None
    assert result.status == "exact"


def test_host2_manifest_runs_tier1_without_coverage_gate():
    _, cases = load_manifest()
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    result = run_manifest_case(host2)
    assert result.outcome == CaseOutcome.PASSED
    assert result.ground_truth_available is False


def test_expect_coverage_fails_without_solver_when_ground_truth_unavailable():
    _, cases = load_manifest()
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    coverage_required = host2.__class__(**{**host2.__dict__, "expect_coverage": True})
    with patch("tests.inference_corpus.run.run_inference_with_artifacts") as run_inference:
        result = run_manifest_case(coverage_required)
        run_inference.assert_not_called()
    assert result.outcome == CaseOutcome.FAILED
    assert result.coverage_reason == COVERAGE_REASON_GROUND_TRUTH_UNAVAILABLE


def test_available_ground_truth_action_not_in_catalog_out_of_search_without_expect_coverage():
    _, cases = load_manifest()
    host51 = next(case for case in cases if case.id == "628580-p1-host51")
    no_expect_coverage = host51.__class__(**{**host51.__dict__, "expect_coverage": False})
    forced_extraction = GroundTruthExtraction(
        available=True,
        ground_truth=(("missing_action", 1),),
    )
    with (
        patch(
            "tests.inference_corpus.run.extract_ground_truth_v1",
            return_value=forced_extraction,
        ),
        patch("tests.inference_corpus.run.run_inference_with_artifacts") as run_inference,
    ):
        result = run_manifest_case(no_expect_coverage)
        run_inference.assert_not_called()
    assert result.outcome == CaseOutcome.OUT_OF_SEARCH_SPACE
    assert result.ground_truth_available is True
    assert result.coverage_reason == COVERAGE_REASON_ACTION_NOT_IN_CATALOG


def test_host51_fixture_ground_truth_in_catalog():
    _, cases = load_manifest()
    host51 = next(case for case in cases if case.id == "628580-p1-host51")
    score_turn = load_turn_fixture(host51.score_turn_path, fixtures_root=FIXTURES_ROOT)
    prior = load_turn_fixture(host51.prior_turn_path, fixtures_root=FIXTURES_ROOT)
    player_id = resolve_player_id(host51, fixtures_root=FIXTURES_ROOT)
    score = score_for_player(score_turn.scores, player_id, host51.id)
    extraction = extract_ground_truth_v1(
        prior_turn=prior,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        complexity="minimal",
    )
    observation = build_inference_observation(score, score_turn)
    catalog = build_action_catalog_from_turn(observation, score_turn)
    coverage = evaluate_catalog_coverage(extraction.ground_truth, catalog)
    assert extraction.available is True
    assert extraction.ground_truth == ()
    assert coverage.in_search_space is True
