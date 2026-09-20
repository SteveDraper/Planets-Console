"""Parent Solve seam: process SAT sessions match thread without storage rebuild."""

from __future__ import annotations

import threading
import time

import pytest
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT, solve_inference_problem
from api.analytics.scores.tier_solve_backend import SCORES_TIER_SOLVE_BACKEND_ENV
from api.compute.sat_gil_overlap import long_enough_cp_model
from api.compute.sat_session import (
    collect_sat_search_assignments,
    int_vars_by_name,
    sat_search_session_wire,
)
from api.compute.sat_session_submit import collect_resolved_sat_search_assignments
from ortools.sat.python import cp_model


def _sum_to_five_model() -> tuple[cp_model.CpModel, tuple[str, str]]:
    model = cp_model.CpModel()
    x = model.new_int_var(0, 5, "x")
    y = model.new_int_var(0, 5, "y")
    model.add(x + y == 5)
    model.maximize(x)
    del x, y
    return model, ("x", "y")


def _rush_problem() -> InferenceProblem:
    return InferenceProblem(
        observation=InferenceObservation(
            player_id=1,
            turn=5,
            military_delta_2x=400,
            warship_delta=1,
            freighter_delta=0,
            priority_point_delta=0,
            starbases_owned=3,
            is_after_ship_limit=False,
        ),
        aggregate_actions=(
            CandidateAction(
                id="build_rush",
                label="Build Rush",
                score_delta_2x=400,
                warship_delta=1,
                build_slot_usage=1,
                upper_bound=1,
            ),
        ),
        max_solutions=20,
        time_limit_seconds=1.0,
    )


def test_thread_resolved_collection_matches_in_process_kernel() -> None:
    model, names = _sum_to_five_model()
    named = int_vars_by_name(model)
    expected = collect_sat_search_assignments(
        model,
        count_vars={name: named[name] for name in names},
        names=names,
        max_solutions=1,
        time_limit_seconds=5.0,
        num_workers=1,
    )

    process_model, process_names = _sum_to_five_model()
    process_named = int_vars_by_name(process_model)
    actual = collect_resolved_sat_search_assignments(
        process_model,
        count_vars={name: process_named[name] for name in process_names},
        names=process_names,
        max_solutions=1,
        time_limit_seconds=5.0,
        num_workers=1,
    )
    assert actual.assignments == expected.assignments
    assert actual.last_solver_status == expected.last_solver_status
    assert actual.stopped_reason == expected.stopped_reason


def test_process_opt_in_collection_matches_thread_without_storage_root() -> None:
    thread_model, thread_names = _sum_to_five_model()
    thread_named = int_vars_by_name(thread_model)
    thread = collect_sat_search_assignments(
        thread_model,
        count_vars={name: thread_named[name] for name in thread_names},
        names=thread_names,
        max_solutions=1,
        time_limit_seconds=5.0,
        num_workers=1,
    )

    process_model, process_names = _sum_to_five_model()
    process_named = int_vars_by_name(process_model)
    wire = sat_search_session_wire(
        model=process_model,
        int_var_names=process_names,
        max_solutions=1,
        time_limit_seconds=5.0,
        num_workers=1,
    )
    assert "storageRoot" not in wire
    actual = collect_resolved_sat_search_assignments(
        process_model,
        count_vars={name: process_named[name] for name in process_names},
        names=process_names,
        max_solutions=1,
        time_limit_seconds=5.0,
        num_workers=1,
        backend="process",
    )
    assert actual.assignments == thread.assignments
    assert actual.last_solver_status == thread.last_solver_status
    assert actual.stopped_reason == thread.stopped_reason


def test_process_opt_in_solve_matches_thread_status_and_solutions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SCORES_TIER_SOLVE_BACKEND_ENV, raising=False)
    thread = solve_inference_problem(_rush_problem())
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    process = solve_inference_problem(_rush_problem())

    assert thread.status == STATUS_EXACT
    assert process.status == thread.status
    assert process.solutions == thread.solutions
    assert process.solutions[0].actions == (
        InferenceSolutionAction(action_id="build_rush", label="Build Rush", count=1),
    )


def test_process_opt_in_submits_one_session_per_collection_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submits: list[object] = []

    def _capture_submit(self: object, run_step: object, job_wire: object) -> object:
        del self
        submits.append(job_wire)
        from api.compute.sat_session import run_sat_search_session

        return run_sat_search_session(job_wire)

    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    monkeypatch.setattr(
        "api.compute.pools.ComputeWorkerPool.submit_process_callable",
        _capture_submit,
    )
    model, names = _sum_to_five_model()
    named = int_vars_by_name(model)
    result = collect_resolved_sat_search_assignments(
        model,
        count_vars={name: named[name] for name in names},
        names=names,
        max_solutions=1,
        time_limit_seconds=5.0,
        num_workers=1,
        backend="process",
    )
    assert len(submits) == 1
    wire = submits[0]
    assert isinstance(wire, dict)
    assert "storageRoot" not in wire
    assert result.assignments
    assert result.stopped_reason == "max_solutions"


def test_inference_cancel_token_stops_process_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    cancel = InferenceCancelToken()
    model = long_enough_cp_model()
    names = tuple(f"x{index}" for index in range(8))
    named = int_vars_by_name(model)

    def _cancel_soon() -> None:
        time.sleep(0.15)
        cancel.cancel()

    watcher = threading.Thread(target=_cancel_soon)
    watcher.start()
    collected = collect_resolved_sat_search_assignments(
        model,
        count_vars={name: named[name] for name in names},
        names=names,
        max_solutions=1,
        time_limit_seconds=30.0,
        num_workers=1,
        cancel_event=cancel,
        backend="process",
    )
    watcher.join(timeout=2.0)
    assert collected.stopped_reason == "cancelled"
    assert collected.assignments == []


def test_sat_session_submit_is_not_on_worker_import_graph() -> None:
    from tests.sat_worker_import_graph import assert_fresh_import_avoids_sat_worker_denylist

    assert_fresh_import_avoids_sat_worker_denylist(
        import_line="from api.compute.sat_worker_entry import spawn_targets",
        exported_name="spawn_targets",
    )
