"""Shared pytest fixtures for API package tests."""

import os
import sys
from pathlib import Path

# ``uv run pytest`` uses the console-script entry point, which breaks
# InterpreterPoolExecutor shareability for module-level test helpers unless
# PYTHONPATH is set before interpreter startup. Re-exec via ``python -m pytest``.
if os.environ.get("_API_PYTEST_REEXEC") != "1":
    argv0 = Path(sys.argv[0]).name
    running_compute_pool_tests = any("test_compute_pools" in arg for arg in sys.argv[1:])
    if argv0 in {"pytest", "py.test"} and running_compute_pool_tests:
        api_root = str(Path(__file__).resolve().parent.parent)
        pythonpath = os.environ.get("PYTHONPATH", "")
        if api_root not in pythonpath.split(os.pathsep):
            pythonpath = f"{api_root}{os.pathsep}{pythonpath}" if pythonpath else api_root
        env = {**os.environ, "_API_PYTEST_REEXEC": "1", "PYTHONPATH": pythonpath}
        os.execve(sys.executable, [sys.executable, "-m", "pytest", *sys.argv[1:]], env)

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


@pytest.fixture(autouse=True)
def _isolate_global_compute_worker_pool(request: pytest.FixtureRequest):
    yield
    if request.path.name != "test_compute_pools.py":
        return
    from api.compute.pools import shutdown_compute_worker_pool_for_tests

    shutdown_compute_worker_pool_for_tests()


@pytest.fixture(autouse=True)
def _isolate_fleet_table_stream_compute_state(request: pytest.FixtureRequest):
    """Reset orchestrator and worker pool between fleet stream tests."""
    if "test_fleet_table_stream" not in request.path.name:
        yield
        return
    from api.analytics.fleet.fleet_table_stream_registry import (
        reset_fleet_table_stream_registry_for_tests,
    )
    from api.analytics.fleet.fleet_table_stream_scheduler import (
        reset_fleet_table_stream_scheduler_for_tests,
    )
    from api.compute.pools import reset_compute_worker_pool_for_tests
    from api.compute.runtime import reset_orchestrators_for_tests

    reset_fleet_table_stream_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=1)
    reset_fleet_table_stream_scheduler_for_tests()
    yield
    reset_fleet_table_stream_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=1)
    reset_fleet_table_stream_scheduler_for_tests()


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
