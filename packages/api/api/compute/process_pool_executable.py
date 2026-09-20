"""Resolve the interpreter ``ProcessPoolExecutor`` must spawn.

Unpackaged processes keep CPython ``sys.executable``. A frozen process host
must not re-exec the windowed GUI bootloader -- that clones AppKit and the
full freeze. Packaged SAT workers are the sibling ``sat_worker`` binary
collected next to the process host.

``set_executable`` alone is not enough: spawn preparation still sends the
parent ``__main__`` (``process_host_entry.py``) as ``init_main_from_path``.
The child would ``run_path`` that into ``sat_worker`` and crash (or load
AppKit if the file existed). Frozen apply also drops those keys.
"""

from __future__ import annotations

import multiprocessing
import multiprocessing.spawn as spawn_mod
import sys
from pathlib import Path

from api.compute.backend_runtime import process_is_frozen

SAT_WORKER_STEM = "sat_worker"
_SPAWN_PARENT_MAIN_KEYS = ("init_main_from_path", "init_main_from_name")


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
    interpreter unchanged). Frozen apply also omits parent ``__main__``
    from spawn preparation so ``sat_worker`` does not reload the GUI entry.
    """
    executable = process_pool_executable()
    if executable is None:
        return None
    multiprocessing.set_executable(executable)
    _omit_process_host_main_from_spawn_preparation()
    return executable


def _omit_process_host_main_from_spawn_preparation() -> None:
    """Drop spawn keys that re-import the process-host ``__main__`` in children.

    ``popen_spawn_posix`` / ``popen_spawn_win32`` look up
    ``multiprocessing.spawn.get_preparation_data`` at launch time.
    """
    current = spawn_mod.get_preparation_data
    if getattr(current, "_omits_process_host_main", False):
        return

    def get_preparation_data(name: str) -> dict[str, object]:
        data = current(name)
        for key in _SPAWN_PARENT_MAIN_KEYS:
            data.pop(key, None)
        return data

    get_preparation_data._omits_process_host_main = True  # type: ignore[attr-defined]
    spawn_mod.get_preparation_data = get_preparation_data
