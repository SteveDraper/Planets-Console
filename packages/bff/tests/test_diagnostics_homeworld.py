"""BFF homeworld layout-prior diagnostics routes (#274)."""

from __future__ import annotations

from api.analytics.homeworld_locator.layout_prior_report import (
    LayoutPriorSearchStats,
    LayoutPriorStopGateInfo,
    LayoutPriorTimingMs,
    build_run_report,
    problem_size_hints,
)
from api.analytics.homeworld_locator.layout_prior_run_history import (
    clear_layout_prior_reports,
    record_layout_prior_report,
    reset_layout_prior_report_history_for_tests,
)
from bff.app import app
from bff.config import BffConfig
from bff.config import set_config as set_bff_config
from fastapi.testclient import TestClient

client = TestClient(app)


def setup_function() -> None:
    set_bff_config(BffConfig(diagnostics_buffer_size=10))
    reset_layout_prior_report_history_for_tests()
    clear_layout_prior_reports()


def teardown_function() -> None:
    clear_layout_prior_reports()
    reset_layout_prior_report_history_for_tests()


def test_layout_prior_reports_empty_for_shell() -> None:
    response = client.get(
        "/diagnostics/homeworld/layout-prior-reports?gameId=680224&perspective=1&turn=40"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["shell"] == {"gameId": 680224, "perspective": 1, "turn": 40}
    assert body["reports"] == []
    assert body["evidenceRefineReports"] == []
    assert body["baselineReports"] == []
    assert body["ensureFailures"] == []
    assert body["evidenceRefineSummary"]["reportCount"] == 0


def test_layout_prior_reports_returns_shell_scoped_wire() -> None:
    report = build_run_report(
        game_id=680224,
        turn=40,
        perspective=1,
        solver="anneal",
        stop_gate=LayoutPriorStopGateInfo(kind="deadline", budget_ms=150),
        stop_reason="deadline",
        timing=LayoutPriorTimingMs(greedy_ms=1.0, sa_ms=140.0, refine_ms=5.0, total_ms=146.0),
        search=LayoutPriorSearchStats(
            sa_steps_attempted=100,
            sa_steps_accepted=40,
            greedy_cost=12.0,
            pre_refine_cost=10.0,
            final_cost=9.5,
            tie_key=((1, 10),),
        ),
        problem_size=problem_size_hints(
            choice_sector_count=3,
            total_possibles=12,
            stand_in_sector_count=2,
            planet_count=200,
            category="standard",
        ),
        incumbent_cost_series=(),
        captured_at="2026-07-28T12:00:00Z",
    )
    record_layout_prior_report(report)
    # Different shell -- must not appear.
    other = build_run_report(
        game_id=1,
        turn=1,
        perspective=1,
        solver="enumerate",
        stop_gate=LayoutPriorStopGateInfo(kind="never"),
        stop_reason="exhausted",
        timing=LayoutPriorTimingMs(greedy_ms=0.0, sa_ms=1.0, refine_ms=0.0, total_ms=1.0),
        search=LayoutPriorSearchStats(
            sa_steps_attempted=4,
            sa_steps_accepted=0,
            greedy_cost=1.0,
            pre_refine_cost=1.0,
            final_cost=1.0,
            tie_key=(),
        ),
        problem_size=problem_size_hints(
            choice_sector_count=1,
            total_possibles=2,
            stand_in_sector_count=0,
            planet_count=10,
            category="epic",
        ),
        incumbent_cost_series=(),
    )
    record_layout_prior_report(other)

    response = client.get(
        "/diagnostics/homeworld/layout-prior-reports?gameId=680224&perspective=1&turn=40"
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["reports"]) == 1
    assert body["reports"][0]["solver"] == "anneal"
    assert body["reports"][0]["stopReason"] == "deadline"
    assert body["reports"][0]["search"]["finalCost"] == 9.5
