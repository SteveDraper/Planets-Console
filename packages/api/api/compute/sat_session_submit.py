"""Parent SAT search seam: in-process kernel or one process-pool session.

The SAT worker must not import this module. Nested process submits go straight
to ``ProcessPoolExecutor`` so a thread-pool worker waiting on SAT cannot
deadlock the DAG work queue.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager

from ortools.sat.python import cp_model

from api.compute.pools import get_compute_worker_pool
from api.compute.profile import ComputeBackend
from api.compute.sat_session import (
    SatSearchCollectionResult,
    SatSessionCancel,
    SatSessionCancelFlag,
    collect_sat_search_assignments,
    run_sat_search_session,
    sat_search_session_wire,
)

_CANCEL_POLL_SECONDS = 0.05
_PROCESS_BACKEND: ComputeBackend = "process"


def collect_resolved_sat_search_assignments(
    model: cp_model.CpModel,
    *,
    count_vars: Mapping[str, cp_model.IntVar],
    names: Sequence[str],
    max_solutions: int,
    time_limit_seconds: float,
    backend: ComputeBackend = "thread",
    objective_var: cp_model.IntVar | None = None,
    near_best_threshold: int = 0,
    num_workers: int | None = None,
    cancel_event: SatSessionCancel | None = None,
    seed_assignments: Sequence[Mapping[str, int]] = (),
) -> SatSearchCollectionResult:
    """Collect assignments with the parent SAT backend.

    Thread keeps the live-model kernel (including in-process cancel). Process
    submits one search session -- not one pool item per inner ``Solve()`` --
    and maps the returned assignments on the parent.
    """
    if backend != _PROCESS_BACKEND:
        return collect_sat_search_assignments(
            model,
            count_vars=count_vars,
            names=names,
            max_solutions=max_solutions,
            time_limit_seconds=time_limit_seconds,
            objective_var=objective_var,
            near_best_threshold=near_best_threshold,
            num_workers=num_workers,
            cancel_event=cancel_event,
            seed_assignments=seed_assignments,
        )
    return _collect_process_session(
        model,
        names=names,
        max_solutions=max_solutions,
        time_limit_seconds=time_limit_seconds,
        objective_var=objective_var,
        near_best_threshold=near_best_threshold,
        num_workers=num_workers,
        cancel_event=cancel_event,
        seed_assignments=seed_assignments,
    )


def _collect_process_session(
    model: cp_model.CpModel,
    *,
    names: Sequence[str],
    max_solutions: int,
    time_limit_seconds: float,
    objective_var: cp_model.IntVar | None,
    near_best_threshold: int,
    num_workers: int | None,
    cancel_event: SatSessionCancel | None,
    seed_assignments: Sequence[Mapping[str, int]],
) -> SatSearchCollectionResult:
    objective_var_name = None if objective_var is None else _named_int_var(objective_var)
    with _process_cancel_flag(cancel_event) as process_cancel:
        wire = sat_search_session_wire(
            model=model,
            int_var_names=names,
            max_solutions=max_solutions,
            time_limit_seconds=time_limit_seconds,
            objective_var_name=objective_var_name,
            near_best_objective_threshold=near_best_threshold,
            seed_assignments=seed_assignments,
            cancel_event=process_cancel,
            num_workers=num_workers,
        )
        raw = get_compute_worker_pool().submit_process_callable(run_sat_search_session, wire)
        if not isinstance(raw, dict):
            raise TypeError("SAT search session process result must be a dict")
        return SatSearchCollectionResult.from_wire(raw)


def _named_int_var(variable: cp_model.IntVar) -> str:
    name = variable.Name()
    if not name:
        raise TypeError("SAT search session objective var must be named")
    return name


@contextmanager
def _process_cancel_flag(
    cancel_event: SatSessionCancel | None,
) -> Iterator[SatSessionCancel | None]:
    """Yield a pickle-safe cancel flag, forwarding a parent token when needed."""
    if cancel_event is None:
        yield None
        return
    if isinstance(cancel_event, SatSessionCancelFlag):
        yield cancel_event
        return

    session_done = threading.Event()
    with SatSessionCancelFlag() as flag:
        if cancel_event.is_set():
            flag.cancel()

        def _forward() -> None:
            while not session_done.is_set():
                if cancel_event.wait(_CANCEL_POLL_SECONDS):
                    flag.cancel()
                    return

        watcher = threading.Thread(target=_forward, name="sat-session-cancel-forward", daemon=True)
        watcher.start()
        try:
            yield flag
        finally:
            session_done.set()
            watcher.join(timeout=1.0)
