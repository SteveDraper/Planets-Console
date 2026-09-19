"""PyInstaller entry for packaged SAT / process-pool workers.

Imports solver, file storage, and the scores ``tier_solve`` job-wire codec
only. Does not import AppKit, FastAPI ``create_app``, or ``server.process_host``.
The parent process host points ``ProcessPoolExecutor`` at this sibling binary
via ``multiprocessing.set_executable``.
"""

from __future__ import annotations

import multiprocessing

from api.analytics.scores.compute_plane.tier_solve_leaf import run_scores_tier_solve_leaf
from api.compute.worker_turn_cache import init_worker_turn_cache

_SPAWN_TARGETS = (run_scores_tier_solve_leaf, init_worker_turn_cache)


def spawn_targets() -> tuple[object, ...]:
    """Callables the parent ``ProcessPoolExecutor`` pickles into this process."""
    return _SPAWN_TARGETS


if __name__ == "__main__":
    multiprocessing.freeze_support()
