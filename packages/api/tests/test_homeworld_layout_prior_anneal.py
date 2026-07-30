"""Phase 2 anneal / refine / stop-gate tests for homeworld layout prior (#270)."""

from __future__ import annotations

import json
import math
import time
from dataclasses import replace
from dataclasses import replace as dc_replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.layout_distributions_asset import (
    CategoryLayoutDistributions,
    SmoothedMetricDistribution,
)
from api.analytics.homeworld_locator.layout_prior import (
    apply_layout_prior_most_probable,
    build_sector_layout_states,
    layout_prior_input_fingerprint,
)
from api.analytics.homeworld_locator.layout_prior_anneal import AnnealingLayoutPriorSolver
from api.analytics.homeworld_locator.layout_prior_cost import evaluate_layout_prior_selection
from api.analytics.homeworld_locator.layout_prior_enumerate import (
    EnumeratingLayoutPriorSolver,
    nearest_mid_choice_ids,
)
from api.analytics.homeworld_locator.layout_prior_problem import LayoutPriorProblem
from api.analytics.homeworld_locator.layout_prior_refine import refine_stand_in_positions
from api.analytics.homeworld_locator.layout_prior_solver import (
    LAYOUT_PRIOR_SOLVER_ANNEAL,
    LAYOUT_PRIOR_SOLVER_ENUMERATE,
    layout_prior_solver_from_name,
)
from api.analytics.homeworld_locator.layout_prior_stop_gate import (
    DeadlineStopGate,
    MaxStepsStopGate,
    NeverStopGate,
)
from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord
from api.concepts.visibility_coverage import planet_scan_origins, visibility_owner_ids
from api.config import get_config
from api.errors import ValidationError
from api.serialization.turn import turn_info_from_json

from tests.test_homeworld_layout_prior import (
    _eligible_turn,
    _planet,
    _stub_layout_asset,
    _view,
)
from tests.test_homeworld_location_evidence import _ship

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


def _build_choice_problem(
    *,
    template_planet,
    sample_turn,
    choice_planets: list[tuple[int, float, float]],
    pin_radius: float = 550.0,
    player_count: int = 11,
    seed_game_id: int = 680224,
    seed_turn: int = 1,
    seed_perspective: int = 1,
):
    """Pin at sector 0 + possibles in one non-pin sector (angles in radians)."""
    turn, _ = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    pin_angle = 0.0
    width = 2.0 * math.pi / player_count
    half = width / 2.0
    pin_planet = _planet(
        template_planet,
        planet_id=1,
        x=int(center[0] + pin_radius * math.cos(pin_angle)),
        y=int(center[1] + pin_radius * math.sin(pin_angle)),
        ownerid=1,
    )
    planets = [pin_planet]
    candidates = [
        HomeworldCandidateRecord(
            planet_id=1,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
        )
    ]
    for planet_id, angle, radius in choice_planets:
        planets.append(
            _planet(
                template_planet,
                planet_id=planet_id,
                x=int(center[0] + radius * math.cos(angle)),
                y=int(center[1] + radius * math.sin(angle)),
            )
        )
        candidates.append(
            HomeworldCandidateRecord(
                planet_id=planet_id,
                perspective=None,
                confidence_tier=CONFIDENCE_POSSIBLE,
            )
        )
    asset = _stub_layout_asset(support_min=400.0, support_max=700.0)
    r_inner, r_outer = asset.center_distance_band("standard")
    planets_by_id = {planet.id: planet for planet in planets}
    states = build_sector_layout_states(
        candidates=tuple(candidates),
        planets_by_id=planets_by_id,
        pin=pin_planet,
        pin_angle=pin_angle,
        player_count=player_count,
        center=center,
        r_inner=r_inner,
        r_outer=r_outer,
        half=half,
        width=width,
        scan_origins=(),
        nebulas=(),
    )
    fingerprint = layout_prior_input_fingerprint(tuple(candidates))
    problem = LayoutPriorProblem(
        sector_states=states,
        planets_by_id=planets_by_id,
        center=center,
        r_inner=r_inner,
        r_outer=r_outer,
        distributions=asset.for_category("standard"),
        origin_distance_evidence_lambda=(
            get_config().homeworld_locator.origin_distance_evidence_lambda
        ),
        seed_game_id=seed_game_id,
        seed_turn=seed_turn,
        seed_perspective=seed_perspective,
        seed_input_fingerprint=fingerprint,
    )
    return problem, turn, planets, candidates, asset, center


def test_temperature_at_progress_mid_budget_above_final() -> None:
    from api.analytics.homeworld_locator.layout_prior_anneal import (
        _TEMPERATURE_FINAL_RATIO,
        temperature_at_progress,
    )

    t0 = 20.0
    mid = temperature_at_progress(t0, 0.5)
    final = temperature_at_progress(t0, 1.0)
    assert final == pytest.approx(t0 * _TEMPERATURE_FINAL_RATIO)
    assert mid > final * 10.0
    assert mid == pytest.approx(t0 * math.sqrt(_TEMPERATURE_FINAL_RATIO))
    assert temperature_at_progress(t0, 0.0) == pytest.approx(t0)


def test_max_steps_budget_progress_starts_at_zero() -> None:
    gate = MaxStepsStopGate(100)
    assert not gate.should_stop()
    assert gate.budget_progress() == pytest.approx(0.0)
    assert not gate.should_stop()
    assert gate.budget_progress() == pytest.approx(0.01)


def test_deadline_budget_progress_advances() -> None:
    gate = DeadlineStopGate(50)
    assert gate.budget_progress() < 0.5
    time.sleep(0.03)
    assert gate.budget_progress() > 0.4


def test_anneal_deterministic_under_max_steps(template_planet, sample_turn) -> None:
    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    choice_planets = [
        (10 + offset, sector_angle + (offset - 2) * 0.02, 550.0 + offset) for offset in range(5)
    ]
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=choice_planets,
        player_count=player_count,
    )
    solver = AnnealingLayoutPriorSolver()
    first = solver.solve(problem, stop_gate=MaxStepsStopGate(25)).solution
    second = solver.solve(problem, stop_gate=MaxStepsStopGate(25)).solution
    assert first.chosen_planet_ids_by_sector == second.chosen_planet_ids_by_sector
    assert first.tie_key == second.tie_key
    assert first.cost == pytest.approx(second.cost)


def test_anneal_improve_or_equal_with_more_steps(template_planet, sample_turn) -> None:
    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    choice_planets = [
        (20 + offset, sector_angle + (offset - 3) * 0.015, 520.0 + 8 * offset)
        for offset in range(6)
    ]
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=choice_planets,
        player_count=player_count,
    )
    solver = AnnealingLayoutPriorSolver()
    few = solver.solve(problem, stop_gate=MaxStepsStopGate(5)).solution
    many = solver.solve(problem, stop_gate=MaxStepsStopGate(80)).solution
    # Compare discrete mid-stand-in costs (refine is outside the gate).
    few_mid = evaluate_layout_prior_selection(problem, few.chosen_planet_ids_by_sector)
    many_mid = evaluate_layout_prior_selection(problem, many.chosen_planet_ids_by_sector)
    assert few_mid is not None and many_mid is not None
    assert many_mid[0] <= few_mid[0] + 1e-12


def test_anneal_selects_outside_enumerator_top4(template_planet, sample_turn) -> None:
    """True layout winner far from sector mid must remain legal for anneal."""
    player_count = 11
    sector_angle = 3.0 * 2.0 * math.pi / player_count
    width = 2.0 * math.pi / player_count
    near = [
        (100 + offset, sector_angle + (offset - 1.5) * (width / 40.0), 550.0) for offset in range(4)
    ]
    far_winner = (999, sector_angle + width * 0.35, 500.0)
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=[*near, far_winner],
        player_count=player_count,
        pin_radius=550.0,
    )
    choice = next(state for state in problem.sector_states if state.kind == "choice")
    capped = set(nearest_mid_choice_ids(choice, problem))
    assert 999 not in capped
    assert 999 in choice.choice_planet_ids

    enum_solution = (
        EnumeratingLayoutPriorSolver().solve(problem, stop_gate=NeverStopGate()).solution
    )
    assert 999 not in enum_solution.chosen_planet_ids_by_sector.values()

    center_metric = SmoothedMetricDistribution(
        sample_count=100,
        support_min=400.0,
        support_max=600.0,
        mean=500.0,
        std=40.0,
    )
    flat = SmoothedMetricDistribution(
        sample_count=1,
        support_min=0.0,
        support_max=2000.0,
        mean=800.0,
        std=1.0e6,
    )
    problem = dc_replace(
        problem,
        distributions=CategoryLayoutDistributions(
            center_distance=center_metric,
            neighbor_separation=flat,
        ),
    )

    with_far = {choice.sector_index: 999}
    with_near = {choice.sector_index: min(capped)}
    far_score = evaluate_layout_prior_selection(problem, with_far)
    near_score = evaluate_layout_prior_selection(problem, with_near)
    assert far_score is not None and near_score is not None
    assert far_score[0] < near_score[0] - 1e-9

    anneal = AnnealingLayoutPriorSolver().solve(problem, stop_gate=MaxStepsStopGate(400)).solution
    assert anneal.chosen_planet_ids_by_sector.get(choice.sector_index) == 999


def test_anneal_max_steps_zero_returns_promptly(template_planet, sample_turn) -> None:
    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    choice_planets = [
        (30 + offset, sector_angle + (offset - 2) * 0.02, 550.0) for offset in range(8)
    ]
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=choice_planets,
        player_count=player_count,
    )
    started = time.perf_counter()
    solution = AnnealingLayoutPriorSolver().solve(problem, stop_gate=MaxStepsStopGate(0)).solution
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert solution.chosen_planet_ids_by_sector
    assert elapsed_ms < 500.0


def test_anneal_empty_neighborhood_exits_promptly(template_planet, sample_turn) -> None:
    """When every choice sector has a single planet, SA must not spin forever."""
    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    # One planet in one non-pin sector => choice set size 1 => empty SA neighborhood.
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=[(40, sector_angle, 550.0)],
        player_count=player_count,
    )
    choice = next(state for state in problem.sector_states if state.kind == "choice")
    assert len(choice.choice_planet_ids) == 1

    started = time.perf_counter()
    result = AnnealingLayoutPriorSolver().solve(problem, stop_gate=NeverStopGate())
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert result.solution.chosen_planet_ids_by_sector.get(choice.sector_index) == 40
    assert result.report.stop_reason == "exhausted"
    assert elapsed_ms < 500.0


def test_deadline_stop_gate_rejects_negative_budget() -> None:
    with pytest.raises(ValidationError, match="budget_ms must be >= 0"):
        DeadlineStopGate(-1)


def test_max_steps_stop_gate_rejects_negative_steps() -> None:
    with pytest.raises(ValidationError, match="max_steps must be >= 0"):
        MaxStepsStopGate(-1)


def test_injected_anneal_without_stop_gate_terminates(template_planet, sample_turn) -> None:
    """Facade must not leave injected anneal on NeverStopGate forever."""
    turn, pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    radius = 550
    orphan = _planet(template_planet, planet_id=2, x=int(center[0]), y=int(center[1] + radius))
    turn = replace(turn, planets=[pin, orphan])
    definite = HomeworldCandidateRecord(
        planet_id=pin.id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    possible = HomeworldCandidateRecord(
        planet_id=orphan.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    view = _view(definite, possible)
    started = time.perf_counter()
    annotated = apply_layout_prior_most_probable(
        (definite, possible),
        turn=turn,
        view=view,
        player_count=11,
        layout_asset=_stub_layout_asset(),
        map_center=center,
        solver=AnnealingLayoutPriorSolver(),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert {row.planet_id for row in annotated if row.is_most_probable} == {orphan.id}
    # Config deadline is 1000ms; allow refine overhead but fail hard on hang.
    assert elapsed_ms < 5000.0


def test_stand_in_refine_improves_or_equals_mid(template_planet, sample_turn) -> None:
    turn, _pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    player_count = 11
    radius = 550
    pin_angle = 0.0
    orphan_angle = 5.0 * 2.0 * math.pi / player_count
    pin_planet = _planet(
        template_planet,
        planet_id=1,
        x=int(center[0] + radius * math.cos(pin_angle)),
        y=int(center[1] + radius * math.sin(pin_angle)),
        ownerid=1,
    )
    orphan = _planet(
        template_planet,
        planet_id=2,
        x=int(center[0] + radius * math.cos(orphan_angle)),
        y=int(center[1] + radius * math.sin(orphan_angle)),
    )
    ship = _ship(
        turn.ships[0] if turn.ships else sample_turn.ships[0],
        ship_id=99,
        x=pin_planet.x,
        y=pin_planet.y,
        ownerid=turn.player.id,
    )
    turn = replace(
        turn,
        settings=replace(turn.settings, planetscanrange=80),
        planets=[pin_planet, orphan],
        ships=[ship],
    )
    asset = _stub_layout_asset()
    r_inner, r_outer = asset.center_distance_band("standard")
    half = math.pi / player_count
    width = 2.0 * math.pi / player_count
    owner_ids = visibility_owner_ids(turn.player.id, turn.relations)
    scan_origins = planet_scan_origins(
        turn.planets,
        turn.ships,
        turn.hulls,
        owner_ids,
        planet_scan_range=float(turn.settings.planetscanrange),
    )
    candidates = (
        HomeworldCandidateRecord(
            planet_id=pin_planet.id,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
        ),
        HomeworldCandidateRecord(
            planet_id=orphan.id,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        ),
    )
    planets_by_id = {pin_planet.id: pin_planet, orphan.id: orphan}
    states = build_sector_layout_states(
        candidates=candidates,
        planets_by_id=planets_by_id,
        pin=pin_planet,
        pin_angle=pin_angle,
        player_count=player_count,
        center=center,
        r_inner=r_inner,
        r_outer=r_outer,
        half=half,
        width=width,
        scan_origins=scan_origins,
        nebulas=(),
    )
    stand_ins = [state for state in states if state.kind == "stand_in"]
    assert stand_ins, "expected at least one empty unobserved stand-in sector"
    problem = LayoutPriorProblem(
        sector_states=states,
        planets_by_id=planets_by_id,
        center=center,
        r_inner=r_inner,
        r_outer=r_outer,
        distributions=asset.for_category("standard"),
        origin_distance_evidence_lambda=(
            get_config().homeworld_locator.origin_distance_evidence_lambda
        ),
        seed_game_id=1,
        seed_turn=1,
        seed_perspective=1,
        seed_input_fingerprint=layout_prior_input_fingerprint(candidates),
    )
    choice = next(state for state in states if state.kind == "choice")
    chosen = {choice.sector_index: orphan.id}
    mid_scored = evaluate_layout_prior_selection(problem, chosen)
    assert mid_scored is not None
    refined = refine_stand_in_positions(problem, chosen)
    refined_scored = evaluate_layout_prior_selection(problem, chosen, stand_in_positions=refined)
    assert refined_scored is not None
    assert refined_scored[0] <= mid_scored[0] + 1e-12
    if any(len(state.stand_in_samples) > 1 for state in stand_ins):
        assert any(
            refined.get(state.sector_index) != state.stand_in_position for state in stand_ins
        ) or refined_scored[0] == pytest.approx(mid_scored[0])


def test_enumerate_solver_still_selectable(template_planet, sample_turn) -> None:
    turn, pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    radius = 550
    orphan = _planet(template_planet, planet_id=2, x=int(center[0]), y=int(center[1] + radius))
    turn = replace(turn, planets=[pin, orphan])
    definite = HomeworldCandidateRecord(
        planet_id=pin.id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    possible = HomeworldCandidateRecord(
        planet_id=orphan.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    view = _view(definite, possible)
    solver = layout_prior_solver_from_name(LAYOUT_PRIOR_SOLVER_ENUMERATE)
    assert isinstance(solver, EnumeratingLayoutPriorSolver)
    annotated = apply_layout_prior_most_probable(
        (definite, possible),
        turn=turn,
        view=view,
        player_count=11,
        layout_asset=_stub_layout_asset(),
        map_center=center,
        solver=solver,
    )
    assert {row.planet_id for row in annotated if row.is_most_probable} == {orphan.id}


def test_layout_prior_continuity_rng_seed_turns() -> None:
    from api.analytics.homeworld_locator.layout_prior import (
        layout_prior_continuity_rng_seed_turns,
    )

    assert layout_prior_continuity_rng_seed_turns(1) == (1,)
    assert layout_prior_continuity_rng_seed_turns(0) == (0,)
    assert layout_prior_continuity_rng_seed_turns(54) == (53, 54)


def test_select_best_layout_prior_solve_result_prefers_lower_cost() -> None:
    from api.analytics.homeworld_locator.layout_prior import select_best_layout_prior_solve_result
    from api.analytics.homeworld_locator.layout_prior_report import (
        LayoutPriorSearchStats,
        LayoutPriorStopGateInfo,
        LayoutPriorTimingMs,
        build_run_report,
        problem_size_hints,
    )
    from api.analytics.homeworld_locator.layout_prior_solver import (
        LayoutPriorSolution,
        LayoutPriorSolveResult,
    )

    def _result(cost: float, planet_id: int) -> LayoutPriorSolveResult:
        solution = LayoutPriorSolution(
            chosen_planet_ids_by_sector={1: planet_id},
            stand_in_positions_by_sector={},
            cost=cost,
            tie_key=((1, planet_id),),
        )
        report = build_run_report(
            game_id=1,
            turn=2,
            perspective=1,
            solver=LAYOUT_PRIOR_SOLVER_ANNEAL,
            stop_gate=LayoutPriorStopGateInfo(kind="max_steps", max_steps=1),
            stop_reason="max_steps",
            timing=LayoutPriorTimingMs(greedy_ms=0.0, sa_ms=0.0, refine_ms=0.0, total_ms=0.0),
            search=LayoutPriorSearchStats(
                sa_steps_attempted=0,
                sa_steps_accepted=0,
                greedy_cost=cost,
                pre_refine_cost=cost,
                final_cost=cost,
                tie_key=solution.tie_key,
            ),
            problem_size=problem_size_hints(
                choice_sector_count=1,
                total_possibles=1,
                stand_in_sector_count=0,
                planet_count=1,
                category="standard",
            ),
            incumbent_cost_series=(),
        )
        return LayoutPriorSolveResult(solution=solution, report=report)

    worse = _result(24.559, 368)
    better = _result(24.429, 493)
    assert select_best_layout_prior_solve_result((worse, better)).solution.cost == pytest.approx(
        24.429
    )
    assert select_best_layout_prior_solve_result((better, worse)).solution.cost == pytest.approx(
        24.429
    )


def test_anneal_facade_runs_two_continuity_solves_on_turn_gt_one(
    template_planet, sample_turn, monkeypatch
) -> None:
    from api.analytics.homeworld_locator.layout_prior_run_history import (
        clear_layout_prior_reports,
        recent_layout_prior_reports,
        reset_layout_prior_report_history_for_tests,
    )

    reset_layout_prior_report_history_for_tests()
    clear_layout_prior_reports()
    turn, pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    radius = 550
    orphan = _planet(template_planet, planet_id=2, x=int(center[0]), y=int(center[1] + radius))
    turn = replace(
        turn,
        planets=[pin, orphan],
        settings=replace(turn.settings, turn=54),
        game=replace(turn.game, id=663307),
    )
    definite = HomeworldCandidateRecord(
        planet_id=pin.id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    possible = HomeworldCandidateRecord(
        planet_id=orphan.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    view = _view(definite, possible)
    solve_calls: list[int | None] = []
    real_solve = AnnealingLayoutPriorSolver.solve

    def tracking_solve(self, problem, *, stop_gate):
        solve_calls.append(problem.rng_seed_turn)
        return real_solve(self, problem, stop_gate=stop_gate)

    monkeypatch.setattr(AnnealingLayoutPriorSolver, "solve", tracking_solve)

    annotated = apply_layout_prior_most_probable(
        (definite, possible),
        turn=turn,
        view=view,
        player_count=11,
        layout_asset=_stub_layout_asset(),
        map_center=center,
        solver=AnnealingLayoutPriorSolver(),
        stop_gate=MaxStepsStopGate(5),
    )
    assert solve_calls == [53, 54]
    assert {row.planet_id for row in annotated if row.is_most_probable} == {orphan.id}
    reports = recent_layout_prior_reports(game_id=663307, turn=54)
    assert len(reports) == 2
    clear_layout_prior_reports()


def test_anneal_facade_single_solve_on_turn_one(template_planet, sample_turn, monkeypatch) -> None:
    turn, pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    radius = 550
    orphan = _planet(template_planet, planet_id=2, x=int(center[0]), y=int(center[1] + radius))
    turn = replace(turn, planets=[pin, orphan])
    definite = HomeworldCandidateRecord(
        planet_id=pin.id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    possible = HomeworldCandidateRecord(
        planet_id=orphan.id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    view = _view(definite, possible)
    solve_calls: list[int | None] = []
    real_solve = AnnealingLayoutPriorSolver.solve

    def tracking_solve(self, problem, *, stop_gate):
        solve_calls.append(problem.rng_seed_turn)
        return real_solve(self, problem, stop_gate=stop_gate)

    monkeypatch.setattr(AnnealingLayoutPriorSolver, "solve", tracking_solve)

    apply_layout_prior_most_probable(
        (definite, possible),
        turn=turn,
        view=view,
        player_count=11,
        layout_asset=_stub_layout_asset(),
        map_center=center,
        solver=AnnealingLayoutPriorSolver(),
        stop_gate=MaxStepsStopGate(5),
    )
    assert solve_calls == [1]


def test_rng_seed_respects_rng_seed_turn_override(template_planet, sample_turn) -> None:
    from api.analytics.homeworld_locator.layout_prior_anneal import layout_prior_rng_seed

    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=[(70, 0.6, 550.0)],
        seed_turn=54,
    )
    base = layout_prior_rng_seed(problem)
    prev = layout_prior_rng_seed(replace(problem, rng_seed_turn=53))
    this = layout_prior_rng_seed(replace(problem, rng_seed_turn=54))
    assert this == base
    assert prev != this
    # Report turn stays shell turn; only RNG hash changes.
    assert replace(problem, rng_seed_turn=53).seed_turn == 54


def test_try_project_previous_layout_selection_admissible(template_planet, sample_turn) -> None:
    from api.analytics.homeworld_locator.layout_prior import try_project_previous_layout_selection

    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=[
            (70, sector_angle, 550.0),
            (71, sector_angle + 0.01, 560.0),
        ],
        player_count=player_count,
    )
    choice = next(state for state in problem.sector_states if state.kind == "choice")
    assert try_project_previous_layout_selection(problem, (70,)) == {choice.sector_index: 70}
    assert try_project_previous_layout_selection(problem, (71,)) == {choice.sector_index: 71}
    assert try_project_previous_layout_selection(problem, (70, 71)) is None
    assert try_project_previous_layout_selection(problem, (999,)) is None
    assert try_project_previous_layout_selection(problem, ()) is None


def test_facade_prefers_admissible_previous_selection_over_worse_anneal(
    template_planet, sample_turn, monkeypatch
) -> None:
    from api.analytics.homeworld_locator.layout_prior import _solve_layout_prior_for_annotation
    from api.analytics.homeworld_locator.layout_prior_report import (
        LayoutPriorSearchStats,
        LayoutPriorStopGateInfo,
        LayoutPriorTimingMs,
        build_run_report,
        problem_size_hints,
    )
    from api.analytics.homeworld_locator.layout_prior_solver import (
        LayoutPriorSolution,
        LayoutPriorSolveResult,
    )

    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=[
            (70, sector_angle, 550.0),
            (71, sector_angle + 0.01, 560.0),
        ],
        player_count=player_count,
        seed_turn=57,
    )
    choice = next(state for state in problem.sector_states if state.kind == "choice")
    assert 70 in choice.choice_planet_ids and 71 in choice.choice_planet_ids

    def fake_solve(self, problem, *, stop_gate):
        solution = LayoutPriorSolution(
            chosen_planet_ids_by_sector={choice.sector_index: 71},
            stand_in_positions_by_sector={},
            cost=100.0,
            tie_key=((choice.sector_index, 71),),
        )
        report = build_run_report(
            game_id=problem.seed_game_id,
            turn=problem.seed_turn,
            perspective=problem.seed_perspective,
            solver=LAYOUT_PRIOR_SOLVER_ANNEAL,
            stop_gate=LayoutPriorStopGateInfo(kind="max_steps", max_steps=1),
            stop_reason="max_steps",
            timing=LayoutPriorTimingMs(greedy_ms=0.0, sa_ms=0.0, refine_ms=0.0, total_ms=0.0),
            search=LayoutPriorSearchStats(
                sa_steps_attempted=0,
                sa_steps_accepted=0,
                greedy_cost=100.0,
                pre_refine_cost=100.0,
                final_cost=100.0,
                tie_key=solution.tie_key,
            ),
            problem_size=problem_size_hints(
                choice_sector_count=1,
                total_possibles=2,
                stand_in_sector_count=0,
                planet_count=3,
                category="standard",
            ),
            incumbent_cost_series=(),
        )
        return LayoutPriorSolveResult(solution=solution, report=report)

    monkeypatch.setattr(AnnealingLayoutPriorSolver, "solve", fake_solve)

    result = _solve_layout_prior_for_annotation(
        AnnealingLayoutPriorSolver(),
        problem,
        template_gate=MaxStepsStopGate(1),
        previous_most_probable_planet_ids=(70,),
    )
    assert result.solution.chosen_planet_ids_by_sector == {choice.sector_index: 70}
    assert result.solution.cost < 100.0
    assert result.report.stop_reason == "projected"
    assert result.report.search.final_cost == pytest.approx(result.solution.cost)
    assert result.report.search.tie_key == result.solution.tie_key
    assert result.report.search.sa_steps_attempted == 0
    assert result.report.search.final_cost != pytest.approx(100.0)
    # Projection runs stand-in refine + evaluation; timing must reflect that work.
    assert result.report.timing.refine_ms > 0.0
    assert result.report.timing.total_ms >= result.report.timing.refine_ms
    assert result.report.timing.greedy_ms == 0.0
    assert result.report.timing.sa_ms == 0.0


def test_facade_projection_win_report_not_anneal_reuse(
    template_planet, sample_turn, monkeypatch
) -> None:
    """Projection win must not return the competing anneal report object."""
    from api.analytics.homeworld_locator.layout_prior import _solve_layout_prior_for_annotation
    from api.analytics.homeworld_locator.layout_prior_report import (
        LayoutPriorSearchStats,
        LayoutPriorStopGateInfo,
        LayoutPriorTimingMs,
        build_run_report,
        problem_size_hints,
    )
    from api.analytics.homeworld_locator.layout_prior_solver import (
        LayoutPriorSolution,
        LayoutPriorSolveResult,
    )

    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=[
            (70, sector_angle, 550.0),
            (71, sector_angle + 0.01, 560.0),
        ],
        player_count=player_count,
        seed_turn=57,
    )
    choice = next(state for state in problem.sector_states if state.kind == "choice")
    anneal_reports: list[object] = []

    def fake_solve(self, problem, *, stop_gate):
        solution = LayoutPriorSolution(
            chosen_planet_ids_by_sector={choice.sector_index: 71},
            stand_in_positions_by_sector={},
            cost=100.0,
            tie_key=((choice.sector_index, 71),),
        )
        report = build_run_report(
            game_id=problem.seed_game_id,
            turn=problem.seed_turn,
            perspective=problem.seed_perspective,
            solver=LAYOUT_PRIOR_SOLVER_ANNEAL,
            stop_gate=LayoutPriorStopGateInfo(kind="max_steps", max_steps=1),
            stop_reason="max_steps",
            timing=LayoutPriorTimingMs(greedy_ms=0.0, sa_ms=1.0, refine_ms=0.0, total_ms=1.0),
            search=LayoutPriorSearchStats(
                sa_steps_attempted=1,
                sa_steps_accepted=0,
                greedy_cost=100.0,
                pre_refine_cost=100.0,
                final_cost=100.0,
                tie_key=solution.tie_key,
            ),
            problem_size=problem_size_hints(
                choice_sector_count=1,
                total_possibles=2,
                stand_in_sector_count=0,
                planet_count=3,
                category="standard",
            ),
            incumbent_cost_series=(),
        )
        anneal_reports.append(report)
        return LayoutPriorSolveResult(solution=solution, report=report)

    monkeypatch.setattr(AnnealingLayoutPriorSolver, "solve", fake_solve)

    result = _solve_layout_prior_for_annotation(
        AnnealingLayoutPriorSolver(),
        problem,
        template_gate=MaxStepsStopGate(1),
        previous_most_probable_planet_ids=(70,),
    )
    assert result.report.stop_reason == "projected"
    assert result.report is not anneal_reports[0]
    assert all(result.report is not report for report in anneal_reports)


def test_facade_anneal_win_keeps_anneal_report(template_planet, sample_turn, monkeypatch) -> None:
    """When anneal beats the projection, return that anneal's report unchanged."""
    from api.analytics.homeworld_locator import layout_prior as layout_prior_mod
    from api.analytics.homeworld_locator.layout_prior import (
        ProjectedLayoutSelection,
        _solve_layout_prior_for_annotation,
    )
    from api.analytics.homeworld_locator.layout_prior_report import (
        LayoutPriorSearchStats,
        LayoutPriorStopGateInfo,
        LayoutPriorTimingMs,
        build_run_report,
        problem_size_hints,
    )
    from api.analytics.homeworld_locator.layout_prior_solver import (
        LayoutPriorSolution,
        LayoutPriorSolveResult,
    )

    player_count = 11
    sector_angle = 2.0 * math.pi / player_count
    problem, *_ = _build_choice_problem(
        template_planet=template_planet,
        sample_turn=sample_turn,
        choice_planets=[
            (70, sector_angle, 550.0),
            (71, sector_angle + 0.01, 560.0),
        ],
        player_count=player_count,
        seed_turn=57,
    )
    choice = next(state for state in problem.sector_states if state.kind == "choice")
    anneal_report_holder: list[object] = []

    def fake_solve(self, problem, *, stop_gate):
        solution = LayoutPriorSolution(
            chosen_planet_ids_by_sector={choice.sector_index: 71},
            stand_in_positions_by_sector={},
            cost=0.01,
            tie_key=((choice.sector_index, 71),),
        )
        report = build_run_report(
            game_id=problem.seed_game_id,
            turn=problem.seed_turn,
            perspective=problem.seed_perspective,
            solver=LAYOUT_PRIOR_SOLVER_ANNEAL,
            stop_gate=LayoutPriorStopGateInfo(kind="max_steps", max_steps=1),
            stop_reason="max_steps",
            timing=LayoutPriorTimingMs(greedy_ms=0.0, sa_ms=1.0, refine_ms=0.0, total_ms=1.0),
            search=LayoutPriorSearchStats(
                sa_steps_attempted=1,
                sa_steps_accepted=1,
                greedy_cost=0.01,
                pre_refine_cost=0.01,
                final_cost=0.01,
                tie_key=solution.tie_key,
            ),
            problem_size=problem_size_hints(
                choice_sector_count=1,
                total_possibles=2,
                stand_in_sector_count=0,
                planet_count=3,
                category="standard",
            ),
            incumbent_cost_series=(),
        )
        anneal_report_holder.append(report)
        return LayoutPriorSolveResult(solution=solution, report=report)

    def worse_projection(problem, chosen_by_sector):
        return ProjectedLayoutSelection(
            solution=LayoutPriorSolution(
                chosen_planet_ids_by_sector=dict(chosen_by_sector),
                stand_in_positions_by_sector={},
                cost=50.0,
                tie_key=tuple(sorted((s, p) for s, p in chosen_by_sector.items())),
            ),
            timing=LayoutPriorTimingMs(greedy_ms=0.0, sa_ms=0.0, refine_ms=0.2, total_ms=0.4),
        )

    monkeypatch.setattr(AnnealingLayoutPriorSolver, "solve", fake_solve)
    monkeypatch.setattr(layout_prior_mod, "score_projected_layout_selection", worse_projection)

    result = _solve_layout_prior_for_annotation(
        AnnealingLayoutPriorSolver(),
        problem,
        template_gate=MaxStepsStopGate(1),
        previous_most_probable_planet_ids=(70,),
    )
    assert result.solution.chosen_planet_ids_by_sector == {choice.sector_index: 71}
    assert result.report is anneal_report_holder[0]
    assert result.report.stop_reason == "max_steps"
    assert result.report.search.final_cost == pytest.approx(0.01)
    assert result.report.search.tie_key == ((choice.sector_index, 71),)
    assert result.report.search.sa_steps_attempted == 1
