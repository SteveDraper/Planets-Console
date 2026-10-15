"""CP-SAT honors max_time_in_seconds on a small model whose search is still open.

The hang fuse sets that parameter and waits for Solve() to return. This test
uses a random 3-SAT instance, not a game model, so a miss is solver behavior.
"""

from __future__ import annotations

import time

from api.compute.sat_gil_overlap import long_enough_cp_model
from ortools.sat.python import cp_model

# Production scores search uses one CP-SAT worker.
_NUM_WORKERS = 1
_TIME_LIMIT_SECONDS = 2.0
# The capped solve is still running at the limit. Instant completion would mean
# this instance no longer exercises the limit.
_MIN_WALL_SECONDS = 1.0
# A search that does not poll the time limit runs far past it. Headroom covers
# a busy machine; it does not cover a multi-minute overshoot.
_MAX_WALL_SECONDS = 8.0
_MAX_BUILD_SECONDS = 0.5


def test_cp_sat_max_time_in_seconds_returns_while_search_is_open() -> None:
    build_started = time.perf_counter()
    model = long_enough_cp_model()
    build_seconds = time.perf_counter() - build_started

    solver = cp_model.CpSolver()
    solver.parameters.num_workers = _NUM_WORKERS
    solver.parameters.max_time_in_seconds = _TIME_LIMIT_SECONDS
    solve_started = time.perf_counter()
    status = solver.solve(model)
    wall_seconds = time.perf_counter() - solve_started

    assert build_seconds < _MAX_BUILD_SECONDS, f"model build took {build_seconds:.3f}s"
    assert status == cp_model.UNKNOWN, solver.status_name(status)
    assert _MIN_WALL_SECONDS <= wall_seconds <= _MAX_WALL_SECONDS, (
        f"Solve wall {wall_seconds:.3f}s with max_time_in_seconds={_TIME_LIMIT_SECONDS} "
        f"(solver.wall_time={solver.wall_time:.3f}s status={solver.status_name(status)})"
    )
    assert _MIN_WALL_SECONDS <= solver.wall_time <= _MAX_WALL_SECONDS, (
        f"solver.wall_time={solver.wall_time:.3f}s"
    )
