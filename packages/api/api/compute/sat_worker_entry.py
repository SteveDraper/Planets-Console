"""PyInstaller entry for packaged SAT / process-pool workers.

Imports the SAT-session worker only. Does not import AppKit, FastAPI
``create_app``, ``server.process_host``, file storage, turn codecs, or scores
orchestration / ``RowRun``. The parent process host points
``ProcessPoolExecutor`` at this sibling binary via ``multiprocessing.set_executable``.
"""

from __future__ import annotations

import multiprocessing

from api.compute.sat_session import run_sat_search_session

_SPAWN_TARGETS = (run_sat_search_session,)


def spawn_targets() -> tuple[object, ...]:
    """Callables the parent ``ProcessPoolExecutor`` pickles into this process."""
    return _SPAWN_TARGETS


if __name__ == "__main__":
    multiprocessing.freeze_support()
