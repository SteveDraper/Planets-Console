"""Console-package occupancy probe: frozen vs ``uv`` GIL overlap and file I/O."""

from __future__ import annotations

import json
import sys
from concurrent.futures import InterpreterPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from api.compute.backend_runtime import process_is_frozen
from api.compute.sat_gil_overlap import measure_sat_gil_overlap
from api.storage.file_json_jobs import time_file_json_jobs

PROBE_FLAG = "--console-package-probe"
OUTPUT_FLAG = "--output"


def run_packaged_runtime_probe(*, storage_root: Path) -> dict[str, Any]:
    """Run Solve GIL overlap, tmp-tree file+JSON jobs, and interpreter import try.

    ``storage_root`` must be a temporary directory, not the console data directory.
    """
    gil = measure_sat_gil_overlap()
    file_json = time_file_json_jobs(storage_root)
    return {
        "pythonProgressedDuringSolve": gil.python_progressed_during_solve,
        "frozen": process_is_frozen(),
        "sysExecutable": sys.executable,
        "fileJson": {
            "jobCount": file_json.job_count,
            "wallSeconds": file_json.wall_seconds,
            "protocolCounts": file_json.protocol_counts,
        },
        "interpreterPoolImportError": _interpreter_pool_import_error(),
        "gil": {
            "overlapFraction": gil.overlap_fraction,
            "solveWallSeconds": gil.solve_wall_seconds,
            "solveStatus": gil.solve_status_name,
            "spinIncrements": gil.spin_increments,
        },
    }


def run_console_package_probe_if_requested(argv: list[str] | None = None) -> int | None:
    """Run the occupancy probe when ``--console-package-probe`` is on argv.

    Returns an exit code when the flag is present, otherwise ``None`` so the
    process host can continue into the normal SPA launch. Uses a tmp tree, not
    the console data directory.
    """
    args = list(sys.argv if argv is None else argv)
    if PROBE_FLAG not in args:
        return None
    output_path = _output_path_from_argv(args)
    with TemporaryDirectory(prefix="console-package-probe-") as tmp:
        payload = run_packaged_runtime_probe(storage_root=Path(tmp))
    text = json.dumps(payload, indent=2) + "\n"
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


def _output_path_from_argv(argv: list[str]) -> Path | None:
    for index, arg in enumerate(argv):
        if arg == OUTPUT_FLAG:
            if index + 1 >= len(argv):
                raise ValueError(f"{OUTPUT_FLAG} requires a path")
            return Path(argv[index + 1])
        prefix = f"{OUTPUT_FLAG}="
        if arg.startswith(prefix):
            value = arg[len(prefix) :]
            if not value:
                raise ValueError(f"{OUTPUT_FLAG} requires a path")
            return Path(value)
    return None


def _interpreter_pool_import_error() -> str | None:
    """Try ``InterpreterPoolExecutor`` + ``import api``; return the exception text."""

    def import_api() -> None:
        import importlib

        importlib.import_module("api")

    try:
        with InterpreterPoolExecutor(max_workers=1, initializer=import_api) as pool:
            pool.submit(bool).result(timeout=30)
    except BaseException as exc:
        return f"{type(exc).__name__}: {exc}"
    return None
