"""SAT leaf: model-build vs Solve split and GIL-overlap characterization."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

from api.analytics.military_score_inference.actions import (
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.models import InferenceProblem
from api.analytics.military_score_inference.solver import (
    _build_model,
    _merge_score_equivalent_combos,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from ortools.sat.python import cp_model

from tests.inference_corpus.fixtures import load_turn_fixture

CORPUS_TURN_PATH = "628580/1/turns/3.json"
CORPUS_PLAYER_ID = 1
EARLY_POLICY_STEP_ID = "early_game_bands"
MIN_MERGED_COMBOS = 100

GIL_SOLVE_CAP_SECONDS = 0.2
GIL_MIN_SOLVE_WALL_SECONDS = 0.1
GIL_MIN_OVERLAP_FRACTION = 0.05
GIL_3SAT_VARS = 250
GIL_3SAT_CLAUSES = 1065
GIL_3SAT_SEED = 0
GIL_CALIBRATION_SECONDS = 0.05


@dataclass(frozen=True)
class SatLeafSplit:
    """Timed catalog-merge + model-build versus one ``Solve()`` on that model."""

    merge_seconds: float
    build_seconds: float
    solve_seconds: float
    raw_combo_count: int
    merged_combo_count: int
    solver_status: int
    solver_status_name: str

    @property
    def python_seconds(self) -> float:
        return self.merge_seconds + self.build_seconds

    @property
    def python_fraction(self) -> float:
        total = self.python_seconds + self.solve_seconds
        return self.python_seconds / total


def _early_game_corpus_problem() -> InferenceProblem:
    turn = load_turn_fixture(CORPUS_TURN_PATH)
    score = next(row for row in turn.scores if row.ownerid == CORPUS_PLAYER_ID)
    observation = build_inference_observation(score, turn)
    early_step = next(step for step in resolve_tier_policies() if step.id == EARLY_POLICY_STEP_ID)
    catalog = build_action_catalog_from_turn(observation, turn, policy_step=early_step)
    return build_inference_problem(observation, catalog, max_solutions=1)


def _time_sat_leaf_split(problem: InferenceProblem) -> SatLeafSplit:
    merge_started = time.perf_counter()
    merged_catalog = _merge_score_equivalent_combos(problem.ship_build_combos)
    merge_seconds = time.perf_counter() - merge_started

    build_started = time.perf_counter()
    built = _build_model(problem, merged_catalog)
    build_seconds = time.perf_counter() - build_started

    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solve_started = time.perf_counter()
    status = solver.solve(built.model)
    solve_seconds = time.perf_counter() - solve_started

    return SatLeafSplit(
        merge_seconds=merge_seconds,
        build_seconds=build_seconds,
        solve_seconds=solve_seconds,
        raw_combo_count=len(problem.ship_build_combos),
        merged_combo_count=len(merged_catalog.combos),
        solver_status=status,
        solver_status_name=solver.status_name(status),
    )


def _long_enough_cp_model() -> cp_model.CpModel:
    """Random 3-SAT near the hard ratio; this venv hits the Solve wall cap."""
    rng = random.Random(GIL_3SAT_SEED)
    model = cp_model.CpModel()
    variables = [model.new_bool_var(f"x{index}") for index in range(GIL_3SAT_VARS)]
    for _ in range(GIL_3SAT_CLAUSES):
        literals = []
        for _ in range(3):
            variable = variables[rng.randrange(GIL_3SAT_VARS)]
            literals.append(variable if rng.random() < 0.5 else variable.Not())
        model.add_bool_or(literals)
    return model


def _uncontended_spin_rate() -> float:
    increments = 0
    started = time.perf_counter()
    while time.perf_counter() - started < GIL_CALIBRATION_SECONDS:
        increments += 1
    return increments / GIL_CALIBRATION_SECONDS


def test_model_build_and_solve_are_separable_on_corpus_catalog():
    problem = _early_game_corpus_problem()
    split = _time_sat_leaf_split(problem)

    assert split.merged_combo_count >= MIN_MERGED_COMBOS, split
    assert split.merge_seconds > 0.0, split
    assert split.build_seconds > 0.0, split
    assert split.solve_seconds > 0.0, split
    assert split.solver_status in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
        cp_model.INFEASIBLE,
        cp_model.UNKNOWN,
    )
    print(
        "sat_leaf_split "
        f"python_fraction={split.python_fraction:.3f} "
        f"merge={split.merge_seconds:.4f}s build={split.build_seconds:.4f}s "
        f"solve={split.solve_seconds:.4f}s status={split.solver_status_name} "
        f"raw_combos={split.raw_combo_count} merged={split.merged_combo_count}",
        flush=True,
    )
    assert 0.0 < split.python_fraction < 1.0, (
        f"SAT leaf python_fraction={split.python_fraction:.3f} "
        f"merge={split.merge_seconds:.4f}s build={split.build_seconds:.4f}s "
        f"solve={split.solve_seconds:.4f}s status={split.solver_status_name} "
        f"raw_combos={split.raw_combo_count} merged={split.merged_combo_count}"
    )


def test_ortools_solve_releases_gil_to_python_thread():
    model = _long_enough_cp_model()
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.max_time_in_seconds = GIL_SOLVE_CAP_SECONDS

    increment_count = 0
    spin_started = threading.Event()
    stop_spin = threading.Event()

    def spin() -> None:
        nonlocal increment_count
        spin_started.set()
        while not stop_spin.is_set():
            increment_count += 1

    spinner = threading.Thread(target=spin)
    spinner.start()
    assert spin_started.wait(timeout=1.0)
    while increment_count == 0:
        time.sleep(0)

    count_before = increment_count
    solve_started = time.perf_counter()
    status = solver.solve(model)
    solve_wall = time.perf_counter() - solve_started
    count_after = increment_count
    stop_spin.set()
    spinner.join()

    progressed = count_after - count_before
    calibrated_rate = _uncontended_spin_rate()
    overlap_fraction = (progressed / solve_wall) / calibrated_rate

    assert solve_wall >= GIL_MIN_SOLVE_WALL_SECONDS, (
        f"Solve was not long enough to probe GIL overlap "
        f"(wall={solve_wall:.3f}s status={solver.status_name(status)})"
    )
    print(
        "sat_leaf_gil_overlap "
        f"overlap_fraction={overlap_fraction:.3f} progressed={progressed} "
        f"wall={solve_wall:.3f}s status={solver.status_name(status)}",
        flush=True,
    )
    assert overlap_fraction >= GIL_MIN_OVERLAP_FRACTION, (
        "Python thread made no substantial progress during Solve; "
        "this venv's OR-Tools is not handing the GIL to another thread "
        f"(overlap_fraction={overlap_fraction:.3f} progressed={progressed} "
        f"wall={solve_wall:.3f}s status={solver.status_name(status)})"
    )
