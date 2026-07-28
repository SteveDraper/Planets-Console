"""Layout-prior solver run report shape, retention, and anneal telemetry (#274)."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.layout_prior import apply_layout_prior_most_probable
from api.analytics.homeworld_locator.layout_prior_anneal import AnnealingLayoutPriorSolver
from api.analytics.homeworld_locator.layout_prior_report import (
    LAYOUT_PRIOR_INCUMBENT_SERIES_MAX_POINTS,
    LAYOUT_PRIOR_REPORT_RING_CAPACITY,
    downsample_incumbent_series,
    layout_prior_report_to_wire,
)
from api.analytics.homeworld_locator.layout_prior_run_history import (
    clear_layout_prior_reports,
    recent_layout_prior_reports,
    record_layout_prior_report,
    reset_layout_prior_report_history_for_tests,
)
from api.analytics.homeworld_locator.layout_prior_stop_gate import MaxStepsStopGate
from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord
from api.serialization.turn import turn_info_from_json
from api.services.layout_prior_diagnostics_service import get_layout_prior_reports_wire

from tests.test_homeworld_layout_prior import _eligible_turn, _planet, _stub_layout_asset, _view
from tests.test_homeworld_layout_prior_anneal import _build_choice_problem

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def template_planet():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    turn = turn_info_from_json(raw, settings_defaults=raw["settings"])
    return turn.planets[0]


@pytest.fixture
def sample_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


@pytest.fixture(autouse=True)
def _clear_report_ring():
    reset_layout_prior_report_history_for_tests()
    clear_layout_prior_reports()
    yield
    clear_layout_prior_reports()
    reset_layout_prior_report_history_for_tests()


def test_downsample_incumbent_series_bounds_length() -> None:
    samples = [(i, float(100 - i)) for i in range(200)]
    down = downsample_incumbent_series(samples, max_points=LAYOUT_PRIOR_INCUMBENT_SERIES_MAX_POINTS)
    assert len(down) <= LAYOUT_PRIOR_INCUMBENT_SERIES_MAX_POINTS
    assert down[0].step == 0
    assert down[-1].step == 199


def test_anneal_run_report_has_timing_costs_stop_reason_and_series(
    template_planet, sample_turn
) -> None:
    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    choice_planets = [
        (50 + offset, sector_angle + (offset - 2) * 0.02, 550.0 + offset) for offset in range(5)
    ]
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=choice_planets,
        player_count=player_count,
        seed_game_id=680224,
        seed_turn=40,
        seed_perspective=1,
    )
    result = AnnealingLayoutPriorSolver().solve(problem, stop_gate=MaxStepsStopGate(40))
    report = result.report
    assert report.solver == "anneal"
    assert report.game_id == 680224
    assert report.turn == 40
    assert report.perspective == 1
    assert report.stop_gate.kind == "max_steps"
    assert report.stop_gate.max_steps == 40
    assert report.stop_reason == "max_steps"
    assert report.timing.total_ms >= 0.0
    assert report.timing.greedy_ms >= 0.0
    assert report.timing.sa_ms >= 0.0
    assert report.timing.refine_ms >= 0.0
    assert report.search.sa_steps_attempted <= 40
    assert report.search.sa_steps_accepted <= report.search.sa_steps_attempted
    assert report.search.final_cost == pytest.approx(result.solution.cost)
    assert report.search.greedy_cost >= 0.0
    assert report.search.pre_refine_cost >= 0.0
    assert 0 <= report.search.last_incumbent_improvement_step <= report.search.sa_steps_attempted
    assert report.problem_size.choice_sector_count >= 1
    assert report.problem_size.total_possibles >= 1
    assert len(report.incumbent_cost_series) >= 1
    assert len(report.incumbent_cost_series) <= LAYOUT_PRIOR_INCUMBENT_SERIES_MAX_POINTS
    wire = layout_prior_report_to_wire(report)
    assert wire["stopReason"] == "max_steps"
    assert wire["search"]["saStepsAttempted"] == report.search.sa_steps_attempted
    assert (
        wire["search"]["lastIncumbentImprovementStep"]
        == report.search.last_incumbent_improvement_step
    )
    assert isinstance(wire["incumbentCostSeries"], list)


def test_apply_layout_prior_records_report_in_ring(template_planet, sample_turn) -> None:
    turn, pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    radius = 550
    orphan = _planet(template_planet, planet_id=2, x=int(center[0]), y=int(center[1] + radius))
    turn = replace(turn, planets=[pin, orphan])
    # Align seed scope on the turn so the report matches shell filters.
    turn = replace(
        turn,
        game=replace(turn.game, id=111),
        settings=replace(turn.settings, turn=2),
        player=replace(turn.player, id=3),
    )
    definite = HomeworldCandidateRecord(
        planet_id=pin.id,
        perspective=3,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    possible = HomeworldCandidateRecord(
        planet_id=orphan.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    view = _view(definite, possible)
    apply_layout_prior_most_probable(
        (definite, possible),
        turn=turn,
        view=view,
        player_count=11,
        layout_asset=_stub_layout_asset(),
        map_center=center,
        solver=AnnealingLayoutPriorSolver(),
        stop_gate=MaxStepsStopGate(10),
    )
    reports = recent_layout_prior_reports(game_id=111, perspective=3, turn=2)
    assert len(reports) == 1
    assert reports[0].solver == "anneal"
    assert reports[0].game_id == 111

    wire = get_layout_prior_reports_wire(game_id=111, perspective=3, turn=2)
    assert wire["shell"] == {"gameId": 111, "perspective": 3, "turn": 2}
    assert len(wire["reports"]) == 1
    assert wire["reports"][0]["gameId"] == 111

    assert recent_layout_prior_reports(game_id=999, perspective=3, turn=2) == ()


def test_report_ring_retains_last_n(template_planet, sample_turn) -> None:
    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=[(70, sector_angle, 550.0), (71, sector_angle + 0.01, 560.0)],
        player_count=player_count,
    )
    solver = AnnealingLayoutPriorSolver()
    for _ in range(LAYOUT_PRIOR_REPORT_RING_CAPACITY + 5):
        record_layout_prior_report(solver.solve(problem, stop_gate=MaxStepsStopGate(2)).report)
    all_reports = recent_layout_prior_reports()
    assert len(all_reports) == LAYOUT_PRIOR_REPORT_RING_CAPACITY
