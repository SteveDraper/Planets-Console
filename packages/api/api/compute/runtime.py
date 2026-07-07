"""Process-wide compute orchestrator wiring for production callers."""

from __future__ import annotations

import threading

from api.analytics.export_context import AnalyticQueryContext
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.pools import ComputeWorkerPool, get_compute_worker_pool
from api.compute.registry import COMPUTE_REGISTRY

_orchestrator_lock = threading.Lock()
_orchestrators_by_ctx_id: dict[int, ComputeOrchestrator] = {}


def orchestrator_for_context(
    ctx: AnalyticQueryContext,
    *,
    worker_pool: ComputeWorkerPool | None = None,
) -> ComputeOrchestrator:
    """Return a compute orchestrator bound to one query context and the global worker pool."""
    ctx_id = id(ctx)
    with _orchestrator_lock:
        existing = _orchestrators_by_ctx_id.get(ctx_id)
        if existing is not None:
            return existing
        pool = worker_pool if worker_pool is not None else get_compute_worker_pool()
        orchestrator = ComputeOrchestrator(
            ctx,
            compute_registry=COMPUTE_REGISTRY,
            worker_pool=pool,
        )
        _orchestrators_by_ctx_id[ctx_id] = orchestrator
        return orchestrator


def release_orchestrator_for_context(ctx: AnalyticQueryContext) -> None:
    """Drop a cached orchestrator for one query context (stream teardown)."""
    with _orchestrator_lock:
        orchestrator = _orchestrators_by_ctx_id.pop(id(ctx), None)
    if orchestrator is None:
        return
    registration_id = orchestrator.pool_registration_id
    worker_pool = orchestrator.worker_pool
    if registration_id is not None and worker_pool is not None:
        worker_pool.unregister(registration_id)


def reset_orchestrators_for_tests() -> None:
    """Clear cached orchestrators (tests only)."""
    with _orchestrator_lock:
        _orchestrators_by_ctx_id.clear()
