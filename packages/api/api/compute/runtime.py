"""Process-wide compute orchestrator wiring for production callers."""

from __future__ import annotations

import threading

from api.compute.diagnostics import compute_diagnostics_enabled, get_compute_diagnostics_controller
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.pools import ComputeWorkerPool, get_compute_worker_pool
from api.compute.registry import COMPUTE_REGISTRY

_orchestrator_lock = threading.Lock()
_process_orchestrator: ComputeOrchestrator | None = None


def get_compute_orchestrator(
    *,
    worker_pool: ComputeWorkerPool | None = None,
) -> ComputeOrchestrator:
    """Return the process-wide compute orchestrator (lazy singleton)."""
    global _process_orchestrator
    with _orchestrator_lock:
        if _process_orchestrator is not None:
            return _process_orchestrator
        pool = worker_pool if worker_pool is not None else get_compute_worker_pool()
        orchestrator = ComputeOrchestrator(
            compute_registry=COMPUTE_REGISTRY,
            worker_pool=pool,
        )
        _process_orchestrator = orchestrator
        if compute_diagnostics_enabled():
            get_compute_diagnostics_controller().bind_orchestrator(orchestrator)
        return orchestrator


def shutdown_compute_orchestrator_for_tests() -> None:
    """Unregister the singleton from the pool and clear process state (tests only)."""
    global _process_orchestrator
    with _orchestrator_lock:
        orchestrator = _process_orchestrator
        _process_orchestrator = None
    if orchestrator is None:
        return
    registration_id = orchestrator.pool_registration_id
    worker_pool = orchestrator.worker_pool
    if registration_id is not None and worker_pool is not None:
        worker_pool.unregister(registration_id)
    orchestrator.turn_cache.clear()
    get_compute_diagnostics_controller().unbind_orchestrator(orchestrator)


def reset_orchestrators_for_tests() -> None:
    """Clear the process-wide orchestrator (tests only; keeps historical name)."""
    shutdown_compute_orchestrator_for_tests()


def reset_compute_orchestrator_for_tests() -> None:
    """Alias for :func:`reset_orchestrators_for_tests`."""
    shutdown_compute_orchestrator_for_tests()
