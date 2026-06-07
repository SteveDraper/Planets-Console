"""Tests for inference corpus ground truth extraction and catalog coverage (#64)."""

from unittest.mock import patch

import pytest
from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_action_catalog_from_turn,
)
from api.analytics.military_score_inference.analytic import (
    build_inference_observation,
    resolve_inference_target_for_host_turn,
)
from api.analytics.military_score_inference.models import CandidateAction

from tests.inference_corpus.case_helpers import score_for_player
from tests.inference_corpus.catalog_coverage import (
    COVERAGE_REASON_ACTION_NOT_IN_CATALOG,
    COVERAGE_REASON_COMBO_NOT_IN_CATALOG,
    COVERAGE_REASON_COUNT_ABOVE_UPPER_BOUND,
    COVERAGE_REASON_GROUND_TRUTH_UNAVAILABLE,
    evaluate_catalog_coverage,
    evaluate_ground_truth_catalog_coverage,
    resolve_coverage_for_case,
)
from tests.inference_corpus.fixtures import load_turn_fixture
from tests.inference_corpus.ground_truth import (
    GroundTruthExtraction,
    extract_ground_truth_v1,
    format_ground_truth_summary,
)
from tests.inference_corpus.manifest import FIXTURES_ROOT, load_manifest, resolve_player_id
from tests.inference_corpus.models import CaseOutcome
from tests.inference_corpus.run import run_discovered_case, run_manifest_case
from tests.inference_corpus.ship_inventory import new_owned_ships, ship_to_build_combo_id


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
    result = evaluate_catalog_coverage((("combo_99_1_none_none_0_0", 1),), catalog)
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


def test_host2_missouri_combo_id_and_summary_label():
    _, cases = load_manifest()
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    prior = load_turn_fixture(host2.prior_turn_path, fixtures_root=FIXTURES_ROOT)
    score_turn = load_turn_fixture(host2.score_turn_path, fixtures_root=FIXTURES_ROOT)
    player_id = resolve_player_id(host2, fixtures_root=FIXTURES_ROOT)
    new_ship = new_owned_ships(prior, score_turn, player_id)[0]
    combo_id = ship_to_build_combo_id(new_ship, score_turn)
    assert combo_id == "combo_13_9_3_6_8_6"
    summary = format_ground_truth_summary(((combo_id, 1),), score_turn=score_turn)
    assert "Missouri Class Battleship" in summary
    assert "Transwarp Drive" in summary
    assert "Plasma Bolt" in summary
    assert "Mark 4 Photon" in summary


def test_seed_host2_strict_ground_truth_available():
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
    new_ship = new_owned_ships(prior, score_turn, player_id)[0]
    combo_id = ship_to_build_combo_id(new_ship, score_turn)
    assert extraction.available is True
    assert extraction.ground_truth == ((combo_id, 1),)


def test_host51_manifest_case_coverage_passes_tier1():
    _, cases = load_manifest()
    host51 = next(case for case in cases if case.id == "628580-p1-host51")
    result = run_manifest_case(host51)
    assert result.outcome == CaseOutcome.PASSED
    assert result.ground_truth_available is True
    assert result.coverage_reason is None
    assert result.status == "exact"


def test_host2_ground_truth_passes_catalog_coverage_with_tier_escalation():
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
    resolved = resolve_inference_target_for_host_turn(
        score,
        score_turn,
        host_turn=host2.host_turn,
    )
    assert resolved is not None
    tier0_catalog = build_action_catalog_from_turn(resolved.observation, resolved.turn_info)
    tier0_coverage = evaluate_catalog_coverage(extraction.ground_truth, tier0_catalog)
    assert tier0_coverage.in_search_space is False
    assert (
        evaluate_ground_truth_catalog_coverage(
            ground_truth=extraction.ground_truth,
            observation=resolved.observation,
            score_turn=resolved.turn_info,
        ).in_search_space
        is True
    )


def test_host2_manifest_runs_tier1_without_coverage_gate():
    _, cases = load_manifest()
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    result = run_manifest_case(host2)
    assert result.outcome == CaseOutcome.PASSED
    assert result.ground_truth_available is True


def test_expect_coverage_fails_without_solver_when_ground_truth_unavailable():
    _, cases = load_manifest()
    host51 = next(case for case in cases if case.id == "628580-p1-host51")
    coverage_required = host51.__class__(**{**host51.__dict__, "expect_coverage": True})
    unavailable_extraction = GroundTruthExtraction(
        available=False,
        unavailable_reason="residual_unexplained",
    )
    with (
        patch(
            "tests.inference_corpus.run.extract_ground_truth_v1",
            return_value=unavailable_extraction,
        ),
        patch("tests.inference_corpus.run.run_inference_with_artifacts") as run_inference,
    ):
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


def test_host2_reported_host_turn_observation_matches_turn_pair_ground_truth():
    from api.analytics.military_score_inference.accelerated_start import (
        accelerated_inference_segments,
    )

    _, cases = load_manifest()
    host2 = next(case for case in cases if case.id == "628580-p1-host2")
    score_turn = load_turn_fixture(host2.score_turn_path, fixtures_root=FIXTURES_ROOT)
    player_id = resolve_player_id(host2, fixtures_root=FIXTURES_ROOT)
    score = score_for_player(score_turn.scores, player_id, host2.id)
    observation = build_inference_observation(score, score_turn)
    segments = accelerated_inference_segments(score, score_turn)
    assert score.militarychange == 4275
    assert observation.military_delta_2x == 2 * score.militarychange == 8550
    assert segments is not None
    assert segments[-1].military_delta_2x == observation.military_delta_2x
    assert segments[0].military_delta_2x == 110


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


CATS_PAW_COMBO_ID = "combo_81_9_6_10_4_2"
REPO_ROOT = FIXTURES_ROOT.parents[4]
P9_TURN1_PATH = REPO_ROOT / ".data" / "games" / "628580" / "9" / "turns" / "1.json"
P8_TURN1_PATH = REPO_ROOT / ".data" / "games" / "628580" / "8" / "turns" / "1.json"
P5_TURN1_PATH = REPO_ROOT / ".data" / "games" / "628580" / "5" / "turns" / "1.json"


@pytest.mark.skipif(not P9_TURN1_PATH.is_file(), reason="local store only")
def test_p9_cats_paw_ground_truth_from_inventory_on_accel_host_turns():
    """Inventory GT ignores unreliable scoreboard militarychange on accel rows."""
    from tests.inference_corpus.storage_loader import (
        configure_file_storage,
        make_game_service,
        make_turn_load_service,
        resolve_player_id_for_case,
    )

    storage = configure_file_storage(storage_root=REPO_ROOT / ".data")
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    player_id = resolve_player_id_for_case(game_service, 628580, 9)

    for host_turn in (1, 2):
        prior = turn_load.get_turn_info(628580, 9, host_turn)
        score_turn = turn_load.get_turn_info(628580, 9, host_turn + 1)
        score = score_for_player(score_turn.scores, player_id, f"628580-p9-host{host_turn}")
        if host_turn == 1:
            assert score.militarychange == 0
        extraction = extract_ground_truth_v1(
            prior_turn=prior,
            score_turn=score_turn,
            player_id=player_id,
            score=score,
            complexity="minimal",
        )
        assert extraction.available is True
        assert extraction.ground_truth == ((CATS_PAW_COMBO_ID, 1),)
        summary = format_ground_truth_summary(extraction.ground_truth, score_turn=score_turn)
        assert "Cat's Paw" in summary
        assert "Transwarp" in summary
        assert "Disruptor" in summary
        assert "Mark 8 Photon" in summary


@pytest.mark.skipif(not P9_TURN1_PATH.is_file(), reason="local store only")
def test_p9_host1_discovered_case_passes_coverage_gate():
    from api.services.store_service import StoreService

    from tests.inference_corpus.discovery import discover_cases_for_game
    from tests.inference_corpus.models import CaseOutcome
    from tests.inference_corpus.storage_loader import (
        configure_file_storage,
        make_game_service,
        make_turn_load_service,
    )

    storage = configure_file_storage(storage_root=REPO_ROOT / ".data")
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    store = StoreService(storage)
    case = next(c for c in discover_cases_for_game(store, 628580) if c.id == "628580-p9-host1")
    result = run_discovered_case(
        case,
        turn_load=turn_load,
        game_service=game_service,
        store=store,
    )
    assert result.outcome != CaseOutcome.OUT_OF_SEARCH_SPACE
    assert result.ground_truth_available is True
    assert result.coverage_reason is None


@pytest.mark.skipif(not P8_TURN1_PATH.is_file(), reason="local store only")
def test_p8_host1_discovered_case_passes_coverage_gate():
    """Five starbase fighters (625 in 2x) fit partition slack when accel window shows 624."""
    from api.services.store_service import StoreService

    from tests.inference_corpus.discovery import discover_cases_for_game
    from tests.inference_corpus.models import CaseOutcome
    from tests.inference_corpus.storage_loader import (
        configure_file_storage,
        make_game_service,
        make_turn_load_service,
    )

    storage = configure_file_storage(storage_root=REPO_ROOT / ".data")
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    store = StoreService(storage)
    case = next(c for c in discover_cases_for_game(store, 628580) if c.id == "628580-p8-host1")
    result = run_discovered_case(
        case,
        turn_load=turn_load,
        game_service=game_service,
        store=store,
    )
    assert result.outcome != CaseOutcome.OUT_OF_SEARCH_SPACE
    assert result.ground_truth_available is True
    assert result.coverage_reason is None


@pytest.mark.skipif(not P5_TURN1_PATH.is_file(), reason="local store only")
def test_p5_host5_discovered_case_passes_coverage_gate():
    """Br5 Kaye build combo is in catalog when buildable hulls use turn.racehulls."""
    from api.services.store_service import StoreService

    from tests.inference_corpus.discovery import discover_cases_for_game
    from tests.inference_corpus.models import CaseOutcome
    from tests.inference_corpus.storage_loader import (
        configure_file_storage,
        make_game_service,
        make_turn_load_service,
    )

    storage = configure_file_storage(storage_root=REPO_ROOT / ".data")
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    store = StoreService(storage)
    case = next(c for c in discover_cases_for_game(store, 628580) if c.id == "628580-p5-host5")
    result = run_discovered_case(
        case,
        turn_load=turn_load,
        game_service=game_service,
        store=store,
    )
    assert result.outcome != CaseOutcome.OUT_OF_SEARCH_SPACE
    assert result.ground_truth_available is True
    assert result.coverage_reason is None
