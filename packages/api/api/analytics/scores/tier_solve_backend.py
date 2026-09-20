"""Resolve the scores ``tier_solve`` compute backend.

Production default is ``thread``. Occupancy / tests may opt into ``process`` via
config or env. Frozen and unpackaged processes share that rule; a packaged
``ProcessPoolExecutor`` spawns the sibling ``sat_worker`` binary rather than
the windowed GUI.
"""

from __future__ import annotations

import os

from api.compute.profile import ComputeBackend
from api.config import get_config

SCORES_TIER_SOLVE_BACKEND_ENV = "PLANETS_CONSOLE_SCORES_TIER_SOLVE_BACKEND"
SCORES_TIER_SOLVE_BACKEND_THREAD: ComputeBackend = "thread"
SCORES_TIER_SOLVE_BACKEND_PROCESS: ComputeBackend = "process"


def resolve_scores_tier_solve_backend() -> ComputeBackend:
    """Return the effective scores SAT search backend for this process.

    ``PLANETS_CONSOLE_SCORES_TIER_SOLVE_BACKEND`` overrides
    ``api.scores_tier_solve_backend`` (default ``thread``). Sampled at the
    parent Solve seam, not when the scores profile is imported. The
    ``tier_solve`` DAG step stays on thread. Packaged spawn uses the sibling
    SAT worker (not the process-host executable).
    """
    raw = os.environ.get(SCORES_TIER_SOLVE_BACKEND_ENV)
    if raw is None:
        raw = get_config().scores_tier_solve_backend
    normalized = str(raw).strip().lower()
    if normalized == SCORES_TIER_SOLVE_BACKEND_PROCESS:
        return SCORES_TIER_SOLVE_BACKEND_PROCESS
    if normalized in {"", SCORES_TIER_SOLVE_BACKEND_THREAD}:
        return SCORES_TIER_SOLVE_BACKEND_THREAD
    raise ValueError(f"scores tier_solve backend must be 'thread' or 'process', got {raw!r}")
