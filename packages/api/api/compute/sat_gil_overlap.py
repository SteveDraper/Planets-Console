"""Characterize whether ``CpSolver.Solve`` releases the GIL to another thread."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

GIL_SOLVE_CAP_SECONDS = 0.2
GIL_MIN_SOLVE_WALL_SECONDS = 0.1
GIL_MIN_OVERLAP_FRACTION = 0.05
GIL_3SAT_VARS = 250
GIL_3SAT_CLAUSES = 1065
GIL_3SAT_SEED = 0
GIL_CALIBRATION_SECONDS = 0.05


@dataclass(frozen=True)
class SatGilOverlap:
    """Result of overlapping a Python spin with one ``Solve()``."""

    python_progressed_during_solve: bool
    overlap_fraction: float
    solve_wall_seconds: float
    solve_status_name: str
    spin_increments: int


def long_enough_cp_model() -> cp_model.CpModel:
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


def uncontended_spin_rate() -> float:
    increments = 0
    started = time.perf_counter()
    while time.perf_counter() - started < GIL_CALIBRATION_SECONDS:
        increments += 1
    return increments / GIL_CALIBRATION_SECONDS


def measure_sat_gil_overlap() -> SatGilOverlap:
    """Run one ``Solve()`` while another thread burns Python, then score overlap."""
    model = long_enough_cp_model()
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
    if not spin_started.wait(timeout=1.0):
        stop_spin.set()
        spinner.join(timeout=1.0)
        raise RuntimeError("Python spin thread did not start during SAT GIL overlap probe")
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
    calibrated_rate = uncontended_spin_rate()
    overlap_fraction = (progressed / solve_wall) / calibrated_rate if solve_wall > 0 else 0.0
    return SatGilOverlap(
        python_progressed_during_solve=overlap_fraction >= GIL_MIN_OVERLAP_FRACTION,
        overlap_fraction=overlap_fraction,
        solve_wall_seconds=solve_wall,
        solve_status_name=solver.status_name(status),
        spin_increments=progressed,
    )
