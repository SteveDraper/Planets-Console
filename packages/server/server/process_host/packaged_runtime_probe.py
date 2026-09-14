"""Console-package occupancy probe: frozen vs ``uv`` GIL overlap and file I/O."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from concurrent.futures import InterpreterPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from api.analytics.fleet.observation_persist_jobs import time_observation_persist_jobs
from api.compute.backend_runtime import process_is_frozen
from api.compute.sat_gil_overlap import SatGilOverlap, measure_sat_gil_overlap
from api.storage.file_json_jobs import (
    LargeDocumentJobTiming,
    open_probe_file_backend,
    time_file_json_jobs,
    time_large_document_jobs,
)

PROBE_FLAG = "--console-package-probe"
OUTPUT_FLAG = "--output"


def run_packaged_runtime_probe(
    *,
    storage_root: Path,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run Solve GIL overlap, tmp-tree file+JSON jobs, large-document jobs, import try.

    ``storage_root`` must be a temporary directory, not the console data directory.
    Large-document jobs time ``json.loads`` / ``deep_copy_value`` / get / put of a
    synthetic ~775 KB / ~38k-node fleet-shaped blob (1-thread and 8-thread).
    Frozen macOS also times GIL + large-document while ``NSApplication.run`` is
    on the main thread (no SPA). ``observationPersist`` times observation_leg
    plus ``FleetPersistencePolicy.persist`` of that document.
    ``checkpoint`` is invoked after CLI measurements and before AppKit-on so a
    later ``NSApplication.run`` abort still leaves a JSON file.
    """
    gil = measure_sat_gil_overlap()
    file_json = time_file_json_jobs(storage_root)
    large_document = time_large_document_jobs(storage_root / "large-document")
    observation_persist = time_observation_persist_jobs(
        open_probe_file_backend(storage_root / "observation-persist")
    )
    payload: dict[str, Any] = {
        "pythonProgressedDuringSolve": gil.python_progressed_during_solve,
        "frozen": process_is_frozen(),
        "sysExecutable": sys.executable,
        "fileJson": {
            "jobCount": file_json.job_count,
            "wallSeconds": file_json.wall_seconds,
            "protocolCounts": file_json.protocol_counts,
        },
        "largeDocument": large_document.to_probe_json(),
        "observationPersist": observation_persist.to_probe_json(),
        "appKitOn": {
            "ran": False,
            "pythonProgressedDuringSolve": None,
            "gil": None,
            "largeDocument": None,
        },
        "interpreterPoolImportError": _interpreter_pool_import_error(),
        "gil": _gil_probe_json(gil),
    }
    if checkpoint is not None:
        checkpoint(payload)
    if _should_run_appkit_on():
        payload["appKitOn"] = _app_kit_on_measurements(storage_root / "appkit-on")
    return payload


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

    def write_payload(payload: dict[str, Any]) -> None:
        text = json.dumps(payload, indent=2) + "\n"
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(text, encoding="utf-8")

    with TemporaryDirectory(prefix="console-package-probe-") as tmp:
        payload = run_packaged_runtime_probe(
            storage_root=Path(tmp),
            checkpoint=write_payload if output_path is not None else None,
        )
    text = json.dumps(payload, indent=2) + "\n"
    write_payload(payload)
    sys.stdout.write(text)
    return 0


def _gil_probe_json(gil: SatGilOverlap) -> dict[str, object]:
    return {
        "overlapFraction": gil.overlap_fraction,
        "solveWallSeconds": gil.solve_wall_seconds,
        "solveStatus": gil.solve_status_name,
        "spinIncrements": gil.spin_increments,
    }


def _should_run_appkit_on() -> bool:
    """Frozen macOS process host only. ``uv`` stays off AppKit (issue 468)."""
    return process_is_frozen() and sys.platform == "darwin"


def _app_kit_on_measurements(storage_root: Path) -> dict[str, object]:
    """GIL + large-document while AppKit runs, or a structured skip."""
    skipped: dict[str, object] = {
        "ran": False,
        "pythonProgressedDuringSolve": None,
        "gil": None,
        "largeDocument": None,
    }
    if not _should_run_appkit_on():
        return skipped

    from server.process_host.native_macos import run_work_while_appkit_runs

    def measure() -> tuple[SatGilOverlap, LargeDocumentJobTiming]:
        return (
            measure_sat_gil_overlap(),
            time_large_document_jobs(storage_root / "large-document"),
        )

    gil, large_document = run_work_while_appkit_runs(measure)
    return {
        "ran": True,
        "pythonProgressedDuringSolve": gil.python_progressed_during_solve,
        "gil": _gil_probe_json(gil),
        "largeDocument": large_document.to_probe_json(),
    }


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
