"""Resolve the interpreter ``ProcessPoolExecutor`` must spawn.

Unpackaged processes keep CPython ``sys.executable``. A frozen process host
must not re-exec the windowed GUI bootloader -- that clones AppKit and the
full freeze. Packaged SAT workers are the sibling ``sat_worker`` binary
collected next to the process host.
"""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

from api.compute.backend_runtime import process_is_frozen

SAT_WORKER_STEM = "sat_worker"


def sat_worker_executable_name() -> str:
    """On-disk name of the sibling SAT worker binary (``.exe`` on Windows)."""
    if sys.platform == "win32":
        return f"{SAT_WORKER_STEM}.exe"
    return SAT_WORKER_STEM


def packaged_sat_worker_path() -> Path:
    """Sibling of ``sys.executable`` named ``sat_worker`` (``.exe`` on Windows)."""
    return Path(sys.executable).resolve().parent / sat_worker_executable_name()


def process_pool_executable() -> str | None:
    """Return the spawn executable, or ``None`` to keep the multiprocessing default.

    Unpackaged: ``None`` (CPython). Frozen: the sibling SAT worker path. Raises
    if that file is missing so a packaged pool cannot fall back to the GUI.
    """
    if not process_is_frozen():
        return None
    path = packaged_sat_worker_path()
    if not path.is_file():
        raise RuntimeError(
            "frozen ProcessPoolExecutor requires the sibling SAT worker "
            f"{path.name}; not found at {path}. Packaged spawn must not "
            "re-exec the windowed process host."
        )
    return str(path)


def apply_process_pool_executable() -> str | None:
    """``multiprocessing.set_executable`` to the SAT worker when frozen.

    Returns the path that was set, or ``None`` when unpackaged (default
    interpreter unchanged).
    """
    executable = process_pool_executable()
    if executable is None:
        return None
    multiprocessing.set_executable(executable)
    return executable
