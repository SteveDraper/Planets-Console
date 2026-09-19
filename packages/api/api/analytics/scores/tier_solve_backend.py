"""Resolve the scores ``tier_solve`` compute backend.

Production default is ``thread``. Occupancy / tests may opt into ``process`` via
config or env. A frozen process stays on ``thread`` so this phase does not start
``ProcessPoolExecutor`` inside a packaged ``.app``.
"""

from __future__ import annotations

import os

from api.compute.backend_runtime import process_is_frozen
from api.compute.profile import ComputeBackend
from api.config import get_config

SCORES_TIER_SOLVE_BACKEND_ENV = "PLANETS_CONSOLE_SCORES_TIER_SOLVE_BACKEND"
SCORES_TIER_SOLVE_BACKEND_THREAD: ComputeBackend = "thread"
SCORES_TIER_SOLVE_BACKEND_PROCESS: ComputeBackend = "process"


def resolve_scores_tier_solve_backend() -> ComputeBackend:
    """Return the declared scores ``tier_solve`` backend for this process.

    Frozen runtimes always stay ``thread``. Otherwise
    ``PLANETS_CONSOLE_SCORES_TIER_SOLVE_BACKEND`` overrides
    ``api.scores_tier_solve_backend`` (default ``thread``).
    """
    if process_is_frozen():
        return SCORES_TIER_SOLVE_BACKEND_THREAD
    raw = os.environ.get(SCORES_TIER_SOLVE_BACKEND_ENV)
    if raw is None:
        raw = get_config().scores_tier_solve_backend
    normalized = str(raw).strip().lower()
    if normalized == SCORES_TIER_SOLVE_BACKEND_PROCESS:
        return SCORES_TIER_SOLVE_BACKEND_PROCESS
    if normalized in {"", SCORES_TIER_SOLVE_BACKEND_THREAD}:
        return SCORES_TIER_SOLVE_BACKEND_THREAD
    raise ValueError(f"scores tier_solve backend must be 'thread' or 'process', got {raw!r}")
