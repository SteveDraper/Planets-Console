"""Catalog-free CP-SAT search session for process SAT workers.

A session is one pickled job: a model proto plus search budget, assignment cap,
optional near-best banding, seed no-goods, and a cancel flag. The collection
kernel loops ``Solve()`` with forbid-previous cuts and calls ``stop_search``
in-process when the flag is set. Parent near-best calls the same kernel on a
live model. The child does not load a turn, catalog, or ``RowRun``.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import Any

from google.protobuf import text_format
from ortools.sat import cp_model_pb2
from ortools.sat.python import cp_model

from api.compute.sat_gil_overlap import invoke_cp_sat_solve

WIRE_MODEL_PROTO = "modelProto"
WIRE_INT_VAR_NAMES = "intVarNames"
WIRE_OBJECTIVE_VAR_NAME = "objectiveVarName"
WIRE_MAX_SOLUTIONS = "maxSolutions"
WIRE_TIME_LIMIT_SECONDS = "timeLimitSeconds"
WIRE_NEAR_BEST_OBJECTIVE_THRESHOLD = "nearBestObjectiveThreshold"
WIRE_SEED_ASSIGNMENTS = "seedAssignments"
WIRE_CANCEL_EVENT = "cancelEvent"
WIRE_NUM_WORKERS = "numWorkers"

WIRE_ASSIGNMENTS = "assignments"
WIRE_LAST_SOLVER_STATUS = "lastSolverStatus"
WIRE_LAST_SOLVER_STATUS_NAME = "lastSolverStatusName"
WIRE_STOPPED_REASON = "stoppedReason"
WIRE_TIME_LIMITED = "timeLimited"
WIRE_TIER_MAX_OBJECTIVE = "tierMaxObjective"

_SUCCESS_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)
_CANCEL_POLL_SECONDS = 0.05


@dataclass(frozen=True)
class SatSearchCollectionResult:
    """In-process result of ``collect_sat_search_assignments``."""

    assignments: list[dict[str, int]]
    last_solver_status: int
    last_solver_status_name: str
    stopped_reason: str
    time_limited: bool
    tier_max_objective: int | None

    def as_wire(self) -> dict[str, object]:
        return {
            WIRE_ASSIGNMENTS: self.assignments,
            WIRE_LAST_SOLVER_STATUS: self.last_solver_status,
            WIRE_LAST_SOLVER_STATUS_NAME: self.last_solver_status_name,
            WIRE_STOPPED_REASON: self.stopped_reason,
            WIRE_TIME_LIMITED: self.time_limited,
            WIRE_TIER_MAX_OBJECTIVE: self.tier_max_objective,
        }


class SatSessionCancelFlag:
    """Pickle-safe cross-process cancel flag for one SAT search session.

    Raw ``multiprocessing.Event`` cannot be pickled into ``ProcessPoolExecutor``
    arguments (spawn requires inheritance). This flag is a one-byte shared
    memory cell: the parent calls ``cancel()``, the child polls ``is_set()`` and
    ``wait()`` and invokes ``CpSolver.stop_search``.
    """

    def __init__(self, *, name: str | None = None) -> None:
        if name is None:
            self._memory = shared_memory.SharedMemory(create=True, size=1)
            self._memory.buf[0] = 0
            self._created = True
        else:
            self._memory = shared_memory.SharedMemory(name=name)
            self._created = False

    def __getstate__(self) -> dict[str, str]:
        return {"name": self._memory.name}

    def __setstate__(self, state: dict[str, str]) -> None:
        self._memory = shared_memory.SharedMemory(name=state["name"], track=False)
        self._created = False

    def cancel(self) -> None:
        self._memory.buf[0] = 1

    def is_set(self) -> bool:
        return self._memory.buf[0] != 0

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            remaining = _CANCEL_POLL_SECONDS
            if deadline is not None:
                remaining = min(remaining, max(0.0, deadline - time.monotonic()))
            time.sleep(remaining)
        return True

    def close(self) -> None:
        try:
            if self._created:
                self._memory.unlink()
        finally:
            self._memory.close()
            self._created = False


def configured_sat_search_workers() -> int:
    """Return CP-SAT ``num_workers`` for one ``Solve()`` call.

    Default is **1**: multi-worker CP-SAT portfolios (LNS) routinely overshoot
    short stream tier ``max_time_in_seconds`` budgets. Parallelism for cold
    ensure / streams belongs on the orchestrator thread pool across per-player
    DAG nodes, not inside one solve. Override with
    ``MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS`` for experiments / batch jobs.

    Callers must set only ``parameters.num_workers``. Also setting the deprecated
    ``num_search_workers`` to a non-zero value makes OR-Tools return
    ``MODEL_INVALID``.
    """
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS")
    if raw is not None:
        return max(1, int(raw))
    return 1


def encode_cp_model_proto(model: cp_model.CpModel) -> bytes:
    """Serialize a CP-SAT model to pickle-safe proto bytes."""
    payload = cp_model_pb2.CpModelProto()
    text_format.Parse(str(model.Proto()), payload)
    return payload.SerializeToString()


def cp_model_from_proto(data: bytes) -> cp_model.CpModel:
    """Rebuild a ``CpModel`` from ``encode_cp_model_proto`` bytes."""
    payload = cp_model_pb2.CpModelProto()
    payload.ParseFromString(data)
    model = cp_model.CpModel()
    if not model.Proto().parse_text_format(text_format.MessageToString(payload)):
        raise ValueError("SAT search session modelProto is not a valid CpModelProto")
    return model


def int_vars_by_name(model: cp_model.CpModel) -> dict[str, cp_model.IntVar]:
    """Map proto variable names to live ``IntVar`` handles."""
    named: dict[str, cp_model.IntVar] = {}
    for index, variable in enumerate(model.Proto().variables):
        name = variable.name
        if name == "":
            continue
        named[name] = model.get_int_var_from_proto_index(index)
    return named


def add_assignment_no_good(
    model: cp_model.CpModel,
    count_vars: Mapping[str, cp_model.IntVar],
    assignment: Mapping[str, int],
    cut_index: int,
) -> None:
    """Forbid one full integer assignment on ``count_vars``."""
    differs: list[cp_model.IntVar] = []
    for var_name, previous_count in assignment.items():
        differs_from_previous = model.new_bool_var(f"diff_{cut_index}_{var_name}")
        model.add(count_vars[var_name] != previous_count).only_enforce_if(differs_from_previous)
        model.add(count_vars[var_name] == previous_count).only_enforce_if(
            differs_from_previous.Not()
        )
        differs.append(differs_from_previous)
    model.add_at_least_one(differs)


def sat_search_session_wire(
    *,
    model: cp_model.CpModel,
    int_var_names: Sequence[str],
    max_solutions: int,
    time_limit_seconds: float,
    objective_var_name: str | None = None,
    near_best_objective_threshold: int = 0,
    seed_assignments: Sequence[Mapping[str, int]] = (),
    cancel_event: object | None = None,
    num_workers: int | None = None,
) -> dict[str, object]:
    """Build a pickle-safe SAT search session job wire from a live model."""
    wire: dict[str, object] = {
        WIRE_MODEL_PROTO: encode_cp_model_proto(model),
        WIRE_INT_VAR_NAMES: tuple(int_var_names),
        WIRE_OBJECTIVE_VAR_NAME: objective_var_name,
        WIRE_MAX_SOLUTIONS: max_solutions,
        WIRE_TIME_LIMIT_SECONDS: time_limit_seconds,
        WIRE_NEAR_BEST_OBJECTIVE_THRESHOLD: near_best_objective_threshold,
        WIRE_SEED_ASSIGNMENTS: tuple(dict(seed) for seed in seed_assignments),
    }
    if cancel_event is not None:
        wire[WIRE_CANCEL_EVENT] = cancel_event
    if num_workers is not None:
        wire[WIRE_NUM_WORKERS] = num_workers
    return wire


def run_sat_search_session(job_wire: dict[str, Any]) -> dict[str, object]:
    """Run one SAT search session from a pickle-safe job wire.

    Skip sentinels and storage-rebuild scores wires must not reach this leaf.
    """
    if job_wire.get("orchestrationSkip") is True:
        raise RuntimeError(
            "SAT search session must not receive orchestrationSkip; "
            "skip sentinels complete on the orchestration plane"
        )
    model_proto = job_wire.get(WIRE_MODEL_PROTO)
    if not isinstance(model_proto, (bytes, bytearray)):
        raise TypeError("SAT search session requires modelProto bytes")

    int_var_names = job_wire.get(WIRE_INT_VAR_NAMES)
    if not isinstance(int_var_names, (list, tuple)) or not int_var_names:
        raise TypeError("SAT search session requires non-empty intVarNames")
    names = tuple(str(name) for name in int_var_names)

    max_solutions_raw = job_wire.get(WIRE_MAX_SOLUTIONS, 1)
    if not isinstance(max_solutions_raw, int) or max_solutions_raw < 1:
        raise TypeError("SAT search session requires positive integer maxSolutions")

    time_limit_raw = job_wire.get(WIRE_TIME_LIMIT_SECONDS, 0.0)
    if not isinstance(time_limit_raw, (int, float)):
        raise TypeError("SAT search session requires numeric timeLimitSeconds")
    time_limit_seconds = float(time_limit_raw)

    threshold_raw = job_wire.get(WIRE_NEAR_BEST_OBJECTIVE_THRESHOLD, 0)
    if not isinstance(threshold_raw, int):
        raise TypeError("SAT search session requires integer nearBestObjectiveThreshold")

    objective_var_name = job_wire.get(WIRE_OBJECTIVE_VAR_NAME)
    if objective_var_name is not None and not isinstance(objective_var_name, str):
        raise TypeError("SAT search session objectiveVarName must be a string or omitted")

    seeds_raw = job_wire.get(WIRE_SEED_ASSIGNMENTS, ())
    if not isinstance(seeds_raw, (list, tuple)):
        raise TypeError("SAT search session seedAssignments must be a sequence")
    seed_assignments = tuple(_assignment_from_wire(seed) for seed in seeds_raw)

    num_workers_raw = job_wire.get(WIRE_NUM_WORKERS)
    if num_workers_raw is None:
        num_workers = configured_sat_search_workers()
    elif isinstance(num_workers_raw, int) and num_workers_raw >= 1:
        num_workers = num_workers_raw
    else:
        raise TypeError("SAT search session numWorkers must be a positive integer")

    cancel_event = job_wire.get(WIRE_CANCEL_EVENT)
    model = cp_model_from_proto(bytes(model_proto))
    named_vars = int_vars_by_name(model)
    count_vars = _require_named_vars(named_vars, names)
    objective_var = None
    if objective_var_name is not None:
        objective_var = _require_named_vars(named_vars, (objective_var_name,))[objective_var_name]

    return collect_sat_search_assignments(
        model,
        count_vars=count_vars,
        names=names,
        objective_var=objective_var,
        max_solutions=max_solutions_raw,
        time_limit_seconds=time_limit_seconds,
        near_best_threshold=threshold_raw,
        num_workers=num_workers,
        cancel_event=cancel_event,
        seed_assignments=seed_assignments,
    ).as_wire()


def _assignment_from_wire(seed: object) -> dict[str, int]:
    if not isinstance(seed, dict):
        raise TypeError("SAT search session seed assignment must be a string-to-int map")
    assignment: dict[str, int] = {}
    for key, value in seed.items():
        if not isinstance(key, str) or not isinstance(value, int):
            raise TypeError("SAT search session seed assignment must be a string-to-int map")
        assignment[key] = value
    return assignment


def _require_named_vars(
    named_vars: Mapping[str, cp_model.IntVar],
    names: Sequence[str],
) -> dict[str, cp_model.IntVar]:
    missing = [name for name in names if name not in named_vars]
    if missing:
        raise TypeError(f"SAT search session missing model variables: {missing!r}")
    return {name: named_vars[name] for name in names}


def _cancel_is_set(cancel_event: object | None) -> bool:
    if cancel_event is None:
        return False
    is_set = getattr(cancel_event, "is_set", None)
    return callable(is_set) and bool(is_set())


def _wait_cancel_or_timeout(cancel_event: object, timeout_seconds: float) -> bool:
    wait = getattr(cancel_event, "wait", None)
    if callable(wait):
        return bool(wait(timeout_seconds))
    time.sleep(timeout_seconds)
    return _cancel_is_set(cancel_event)


class _StopSearchOnCancel(cp_model.CpSolverSolutionCallback):
    def __init__(self, cancel_event: object) -> None:
        super().__init__()
        self._cancel_event = cancel_event

    def on_solution_callback(self) -> None:
        if _cancel_is_set(self._cancel_event):
            self.StopSearch()


def collect_sat_search_assignments(
    model: cp_model.CpModel,
    *,
    count_vars: Mapping[str, cp_model.IntVar],
    names: Sequence[str],
    max_solutions: int,
    time_limit_seconds: float,
    objective_var: cp_model.IntVar | None = None,
    near_best_threshold: int = 0,
    num_workers: int | None = None,
    cancel_event: object | None = None,
    seed_assignments: Sequence[Mapping[str, int]] = (),
) -> SatSearchCollectionResult:
    """Collect distinct assignments with forbid-previous and optional near-best banding.

    Catalog-free kernel for process SAT workers and in-process parent near-best.
    Seeds, remaining time, ``stop_search`` cancel watch, and banding all live here.
    """
    for seed_index, seed in enumerate(seed_assignments):
        add_assignment_no_good(model, count_vars, seed, cut_index=-(seed_index + 1))
    workers = configured_sat_search_workers() if num_workers is None else num_workers
    solver = cp_model.CpSolver()
    assignments: list[dict[str, int]] = []
    started_at = time.monotonic()
    last_solver_status = cp_model.UNKNOWN
    stopped_reason = "exhausted"
    time_limited = False
    tier_max_objective: int | None = None
    max_objective: int | None = None
    near_best_band_applied = False
    session_done = threading.Event()
    watcher: threading.Thread | None = None
    if cancel_event is not None:

        def _watch() -> None:
            while not session_done.is_set():
                if _wait_cancel_or_timeout(cancel_event, _CANCEL_POLL_SECONDS):
                    solver.stop_search()
                    return

        watcher = threading.Thread(target=_watch, name="sat-session-cancel", daemon=True)
        watcher.start()

    try:
        while len(assignments) < max_solutions:
            if _cancel_is_set(cancel_event):
                stopped_reason = "cancelled"
                break

            elapsed_seconds = time.monotonic() - started_at
            remaining_seconds = time_limit_seconds - elapsed_seconds
            if remaining_seconds <= 0:
                time_limited = True
                stopped_reason = "time_budget"
                break

            solver.parameters.max_time_in_seconds = remaining_seconds
            solver.parameters.num_workers = workers
            callback = _StopSearchOnCancel(cancel_event) if cancel_event is not None else None
            last_solver_status = invoke_cp_sat_solve(solver, model, callback)

            if _cancel_is_set(cancel_event):
                stopped_reason = "cancelled"
                break
            if last_solver_status not in _SUCCESS_STATUSES:
                if last_solver_status == cp_model.UNKNOWN and assignments:
                    time_limited = True
                    stopped_reason = "time_budget"
                elif near_best_band_applied and assignments:
                    stopped_reason = "near_best_band_exhausted"
                else:
                    stopped_reason = "infeasible"
                break

            if last_solver_status == cp_model.FEASIBLE:
                elapsed_seconds = time.monotonic() - started_at
                if elapsed_seconds >= time_limit_seconds:
                    time_limited = True
                    stopped_reason = "time_budget"

            assignment = {name: int(solver.value(count_vars[name])) for name in names}
            assignments.append(assignment)

            if objective_var is not None:
                found_objective = int(solver.ObjectiveValue())
                if tier_max_objective is None:
                    tier_max_objective = found_objective
                    max_objective = found_objective
                    model.add(objective_var >= tier_max_objective - near_best_threshold)
                    near_best_band_applied = True
                else:
                    max_objective = found_objective
                if near_best_band_applied and max_objective is not None:
                    model.add(objective_var <= max_objective)

            add_assignment_no_good(model, count_vars, assignment, len(assignments))

            if time_limited:
                break
            if len(assignments) >= max_solutions:
                stopped_reason = "max_solutions"
                break
    finally:
        session_done.set()
        if watcher is not None:
            watcher.join(timeout=1.0)

    return SatSearchCollectionResult(
        assignments=assignments,
        last_solver_status=last_solver_status,
        last_solver_status_name=cp_model.CpSolver().status_name(last_solver_status),
        stopped_reason=stopped_reason,
        time_limited=time_limited,
        tier_max_objective=tier_max_objective,
    )
