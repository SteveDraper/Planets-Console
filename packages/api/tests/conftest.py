"""Shared pytest fixtures for API package tests."""

import pytest

from tests.fixtures.hand_seeded_prior_weights import (  # noqa: F401
    HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    HAND_SEEDED_STANDARD_PRIOR_PATH,
)
from tests.fixtures.military_score_inference import (  # noqa: F401
    first_turn,
    sample_turn,
    synthetic_catalog_build_context,
    synthetic_catalog_context,
)
from tests.fixtures.military_score_inference_prior_weights import (  # noqa: F401
    minimal_prior_catalog,
)

pytest_plugins = ["tests.scores_exports_helpers"]

# OR-Tools / inference-corpus integration tests excluded from `make ci` (see Makefile `test_api`).
_SLOW_TEST_NAMES = frozenset(
    {
        "test_628580_accel_window_ranks_ten_planet_defense_first",
        "test_corpus_case_still_infers_exact_with_accelerated_adjustment",
        "test_ensure_prior_turn_sync_passes_fleet_torp_input_status",
        "test_ensure_prior_turn_sync_puts_persistable_row",
        "test_fixed_corpus_coverage_case_has_ground_truth_available",
        "test_fixed_corpus_host2_hard_ranking_lock_passes",
        "test_fixed_inference_corpus_tier1_passes",
        "test_get_scores_row_inference_emits_applied_fleet_torp_input_status",
        "test_host2_manifest_runs_tier1_without_coverage_gate",
        "test_inference_diagnostics_include_policy_ladder_fields",
        "test_inference_overlay_changes_diagnostics_vs_empty_overlay",
        "test_listing_for_case_uses_player_perspective_for_ground_truth",
        "test_manifest_host1_passes_ranking_with_require_top_k",
        "test_mask_change_integration_via_table_stream_generator_case_3",
        "test_missouri_host_turn_2_regression_becomes_feasible",
        "test_missouri_host_turn_2_regression_reports_policy_ladder_diagnostics",
        "test_p5_host5_discovered_case_passes_coverage_gate",
        "test_p8_host1_discovered_case_passes_coverage_gate",
        "test_p9_host1_discovered_case_passes_coverage_gate",
        "test_row_inference_includes_structured_solver_diagnostics",
        "test_run_discovered_case_resolves_ground_truth_from_player_perspective",
        "test_run_local_corpus_discovers_and_passes_seed_case",
        "test_scores_row_inference_returns_solver_payload",
        "test_solve_with_policy_ladder_continues_when_aggregate_actions_are_added",
        "test_solve_with_policy_ladder_fleet_torp_overlay_belief_set",
        "test_stream_recompute_reschedules_after_fleet_overlay_lands",
        "test_unreliable_turn2_backfills_host_turn1_when_turn3_stored",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.name in _SLOW_TEST_NAMES:
            item.add_marker(pytest.mark.slow)
