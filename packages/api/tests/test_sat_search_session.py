"""SAT-session process worker: proto wire, search loop, cancel, import graph."""

from __future__ import annotations

import pickle
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import pytest
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.compute.sat_gil_overlap import invoke_cp_sat_solve, long_enough_cp_model
from api.compute.sat_session import (
    WIRE_ASSIGNMENTS,
    WIRE_LAST_SOLVER_STATUS,
    WIRE_STOPPED_REASON,
    SatSessionCancelFlag,
    add_assignment_no_good,
    collect_sat_search_assignments,
    int_vars_by_name,
    run_sat_search_session,
    sat_search_session_wire,
)
from api.compute.sat_worker_entry import spawn_targets
from ortools.sat.python import cp_model

from tests.sat_worker_import_graph import assert_fresh_import_avoids_sat_worker_denylist

_SUCCESS_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)


def _sum_to_five_model() -> tuple[cp_model.CpModel, tuple[str, str]]:
    model = cp_model.CpModel()
    x = model.new_int_var(0, 5, "x")
    y = model.new_int_var(0, 5, "y")
    model.add(x + y == 5)
    model.maximize(x)
    del x, y
    return model, ("x", "y")


def _distinct_pairs_model() -> tuple[cp_model.CpModel, tuple[str, str], str]:
    model = cp_model.CpModel()
    x = model.new_int_var(0, 2, "x")
    y = model.new_int_var(0, 2, "y")
    objective = model.new_int_var(0, 4, "obj")
    model.add(x + y == 2)
    model.add(objective == x + y)
    model.maximize(objective)
    del x, y, objective
    return model, ("x", "y"), "obj"


def _collect_live_assignments(
    model: cp_model.CpModel,
    names: tuple[str, ...],
    *,
    max_solutions: int,
) -> tuple[list[dict[str, int]], int]:
    named = int_vars_by_name(model)
    count_vars = {name: named[name] for name in names}
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    hits: list[dict[str, int]] = []
    last_status = cp_model.UNKNOWN
    for cut_index in range(max_solutions):
        last_status = invoke_cp_sat_solve(solver, model)
        if last_status not in _SUCCESS_STATUSES:
            break
        assignment = {name: int(solver.value(count_vars[name])) for name in names}
        hits.append(assignment)
        add_assignment_no_good(model, count_vars, assignment, cut_index + 1)
    return hits, last_status


def test_sat_session_import_does_not_load_http_or_parent_plane():
    assert_fresh_import_avoids_sat_worker_denylist(
        import_line="from api.compute.sat_session import run_sat_search_session",
        exported_name="run_sat_search_session",
    )


def test_sat_worker_entry_import_does_not_load_storage_or_ladder():
    assert_fresh_import_avoids_sat_worker_denylist(
        import_line="from api.compute.sat_worker_entry import spawn_targets",
        exported_name="spawn_targets",
    )


def test_spawn_targets_are_sat_search_session():
    assert spawn_targets() == (run_sat_search_session,)


def test_session_round_trip_matches_invoke_cp_sat_solve() -> None:
    live, names = _sum_to_five_model()
    named = int_vars_by_name(live)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    live_status = invoke_cp_sat_solve(solver, live)
    live_assignment = {name: int(solver.value(named[name])) for name in names}

    session_model, session_names = _sum_to_five_model()
    wire = sat_search_session_wire(
        model=session_model,
        int_var_names=session_names,
        max_solutions=1,
        time_limit_seconds=5.0,
        num_workers=1,
    )
    pickle.dumps(wire)
    result = run_sat_search_session(wire)

    assert result[WIRE_LAST_SOLVER_STATUS] == live_status
    assert result[WIRE_ASSIGNMENTS] == [live_assignment]
    assert result[WIRE_STOPPED_REASON] == "max_solutions"


def test_session_near_best_collection_matches_live_no_good_loop() -> None:
    live, names, _objective = _distinct_pairs_model()
    expected, last_status = _collect_live_assignments(live, names, max_solutions=3)

    session_model, session_names, objective_name = _distinct_pairs_model()
    result = run_sat_search_session(
        sat_search_session_wire(
            model=session_model,
            int_var_names=session_names,
            objective_var_name=objective_name,
            max_solutions=3,
            time_limit_seconds=5.0,
            near_best_objective_threshold=0,
            num_workers=1,
        )
    )

    assert result[WIRE_LAST_SOLVER_STATUS] == last_status
    actual = {tuple(sorted(item.items())) for item in result[WIRE_ASSIGNMENTS]}
    expect = {tuple(sorted(item.items())) for item in expected}
    assert actual == expect
    assert len(result[WIRE_ASSIGNMENTS]) == 3
    assert result[WIRE_STOPPED_REASON] == "max_solutions"


def test_session_raises_without_model_proto() -> None:
    with pytest.raises(TypeError, match="modelProto"):
        run_sat_search_session({"runId": "open-evidence", "storageRoot": "/tmp"})


def test_session_raises_on_orchestration_skip() -> None:
    with pytest.raises(RuntimeError, match="orchestration plane"):
        run_sat_search_session({"orchestrationSkip": True, "runId": None})


def test_in_process_session_cancel_stops_search() -> None:
    cancel = threading.Event()
    model = long_enough_cp_model()
    names = tuple(f"x{index}" for index in range(8))
    wire = sat_search_session_wire(
        model=model,
        int_var_names=names,
        max_solutions=1,
        time_limit_seconds=30.0,
        cancel_event=cancel,
        num_workers=1,
    )

    def _cancel_soon() -> None:
        time.sleep(0.15)
        cancel.set()

    watcher = threading.Thread(target=_cancel_soon)
    watcher.start()
    result = run_sat_search_session(wire)
    watcher.join(timeout=2.0)
    assert result[WIRE_STOPPED_REASON] == "cancelled"
    assert result[WIRE_ASSIGNMENTS] == []


def test_process_session_cancel_stops_search_without_hanging_the_pool() -> None:
    context = get_context("spawn")
    cancel = SatSessionCancelFlag()
    model = long_enough_cp_model()
    names = tuple(f"x{index}" for index in range(8))
    try:
        wire = sat_search_session_wire(
            model=model,
            int_var_names=names,
            max_solutions=1,
            time_limit_seconds=30.0,
            cancel_event=cancel,
            num_workers=1,
        )
        pickle.dumps(wire)
        with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
            future = pool.submit(run_sat_search_session, wire)
            time.sleep(0.15)
            cancel.cancel()
            result = future.result(timeout=10.0)
        assert result[WIRE_STOPPED_REASON] == "cancelled"
        assert result[WIRE_ASSIGNMENTS] == []
    finally:
        cancel.close()


def test_collect_sat_search_assignments_matches_session_wire() -> None:
    live, names = _sum_to_five_model()
    named = int_vars_by_name(live)
    collected = collect_sat_search_assignments(
        live,
        count_vars={name: named[name] for name in names},
        names=names,
        max_solutions=1,
        time_limit_seconds=5.0,
        num_workers=1,
    )
    session_model, session_names = _sum_to_five_model()
    wire_result = run_sat_search_session(
        sat_search_session_wire(
            model=session_model,
            int_var_names=session_names,
            max_solutions=1,
            time_limit_seconds=5.0,
            num_workers=1,
        )
    )
    assert collected.as_wire()[WIRE_ASSIGNMENTS] == wire_result[WIRE_ASSIGNMENTS]
    assert collected.stopped_reason == wire_result[WIRE_STOPPED_REASON]
    assert collected.last_solver_status == wire_result[WIRE_LAST_SOLVER_STATUS]


def test_inference_cancel_token_stops_in_process_kernel() -> None:
    cancel = InferenceCancelToken()
    model = long_enough_cp_model()
    names = tuple(f"x{index}" for index in range(8))
    named = int_vars_by_name(model)

    def _cancel_soon() -> None:
        time.sleep(0.15)
        cancel.cancel()

    watcher = threading.Thread(target=_cancel_soon)
    watcher.start()
    collected = collect_sat_search_assignments(
        model,
        count_vars={name: named[name] for name in names},
        names=names,
        max_solutions=1,
        time_limit_seconds=30.0,
        num_workers=1,
        cancel_event=cancel,
    )
    watcher.join(timeout=2.0)
    assert collected.stopped_reason == "cancelled"
    assert collected.assignments == []
