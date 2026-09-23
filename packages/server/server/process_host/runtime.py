"""Process host runtime: packaged config, uvicorn worker, OS event loop."""

from __future__ import annotations

import faulthandler
import logging
import os
import signal
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import uvicorn
from api import config as api_config
from bff import config as bff_config

from server.app import create_app
from server.cli import GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
from server.config import load_packaged_config
from server.console_data_directory import console_data_directory
from server.package_identity import CONSOLE_PACKAGE_DISPLAY_NAME, console_package_version
from server.process_host.bundled_paths import apply_frontend_dist_env
from server.process_host.loopback import (
    LOOPBACK_HOST,
    PREFERRED_PORT,
    HealthWaitError,
    LoopbackBindError,
    next_free_loopback_port,
    open_spa,
    wait_for_health,
)
from server.process_host.single_instance import (
    LOCK_FILE_NAME,
    SingleInstanceLock,
    SingleInstancePortError,
    read_published_port,
)
from server.process_host.support import StartFailure, configure_support_logging, show_start_failure

_LOGGER = logging.getLogger("server.process_host")

# Measurement launches pass this so the SPA does not open a second table stream.
NO_BROWSER_FLAG = "--no-browser"
# When set to a file path, SIGUSR1 appends an all-thread Python traceback there.
TRACE_DUMP_ENV = "PLANETS_CONSOLE_TRACE_DUMP"
# faulthandler writes this fd from the signal handler, so it stays open for the process.
_trace_dump_file: TextIO | None = None


def browser_open_requested(argv: list[str] | None = None) -> bool:
    """Return whether this launch should open the SPA in the default browser."""
    args = sys.argv if argv is None else argv
    return NO_BROWSER_FLAG not in args


def exit_without_interpreter_teardown(code: int = 0) -> None:
    """End the process without CPython ``Py_Finalize`` module GC.

    Packaged heaps can be many gigabytes after a long session. Interpreter
    shutdown then holds the GIL in ``gc_collect_main`` for minutes after OS
    Quit has already stopped uvicorn. ``os._exit`` skips that sweep.
    """
    for handler in logging.root.handlers:
        try:
            handler.flush()
        except OSError:
            pass
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.flush()
        except OSError:
            pass
    os._exit(code)


@dataclass
class ProcessHostSession:
    """Callbacks the native event loop uses to stop uvicorn or reopen the SPA."""

    port: int
    server: uvicorn.Server | None
    stop_event: threading.Event

    def request_stop(self) -> None:
        self.stop_event.set()
        if self.server is not None:
            self.server.should_exit = True

    def reopen_browser(self) -> None:
        if not browser_open_requested():
            _LOGGER.info("Skipping browser reopen (%s)", NO_BROWSER_FLAG)
            return
        open_spa(self.port)


def main() -> int:
    """Entry for the packaged process host. Returns a process exit code."""
    # Literal matches packaged_runtime_probe.PROBE_FLAG; keep this check lazy so
    # a normal launch does not import the occupancy probe (OR-Tools + SAT).
    if "--console-package-probe" in sys.argv:
        from server.process_host.packaged_runtime_probe import (
            run_console_package_probe_if_requested,
        )

        exit_code = run_console_package_probe_if_requested(sys.argv)
        if exit_code is None:
            raise RuntimeError("console-package probe flag was set but the probe declined")
        return exit_code
    try:
        return _run()
    except StartFailure as exc:
        show_start_failure(str(exc))
        return 1
    except Exception as exc:
        _LOGGER.exception("Process host crashed")
        show_start_failure(
            f"{CONSOLE_PACKAGE_DISPLAY_NAME} could not start.\n\n{exc}\n\n"
            "See logs in the Planets Console data folder."
        )
        return 1


def _run() -> int:
    data_dir = console_data_directory()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = configure_support_logging(data_dir)
    _LOGGER.info(
        "Starting %s %s",
        CONSOLE_PACKAGE_DISPLAY_NAME,
        console_package_version(),
    )
    lock = SingleInstanceLock(data_dir / LOCK_FILE_NAME)
    if not lock.try_acquire():
        return _reopen_existing_instance(lock.port_path)

    try:
        return _run_as_primary(lock, log_path)
    finally:
        lock.release()


def _reopen_existing_instance(port_path: Path) -> int:
    try:
        port = read_published_port(port_path)
        wait_for_health(port, timeout_seconds=30.0)
        if browser_open_requested():
            open_spa(port)
        else:
            _LOGGER.info("Skipping browser reopen of existing instance (%s)", NO_BROWSER_FLAG)
        return 0
    except (SingleInstancePortError, HealthWaitError) as exc:
        raise StartFailure(
            f"{CONSOLE_PACKAGE_DISPLAY_NAME} is already running but could not "
            f"reopen the browser.\n\n{exc}"
        ) from exc


def _run_as_primary(lock: SingleInstanceLock, log_path: Path) -> int:
    dist = apply_frontend_dist_env()
    if not dist.is_dir():
        raise StartFailure(f"{CONSOLE_PACKAGE_DISPLAY_NAME} is missing the web UI files at {dist}.")
    try:
        port = next_free_loopback_port(PREFERRED_PORT)
    except LoopbackBindError as exc:
        raise StartFailure(str(exc)) from exc
    lock.write_bound_port(port)
    _configure_packaged_server(port)
    server = _build_uvicorn_server(port)
    session = ProcessHostSession(port=port, server=server, stop_event=threading.Event())
    thread = threading.Thread(target=server.run, name="uvicorn-process-host", daemon=True)
    thread.start()
    try:
        wait_for_health(port)
    except HealthWaitError as exc:
        session.request_stop()
        thread.join(timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)
        raise StartFailure(
            f"{CONSOLE_PACKAGE_DISPLAY_NAME} did not become ready.\n\n{exc}\n\nLog file: {log_path}"
        ) from exc
    if browser_open_requested():
        open_spa(port)
    else:
        _LOGGER.info("Skipping browser open (%s)", NO_BROWSER_FLAG)
    _arm_sigusr1_trace_dump()
    _run_native_loop(session)
    session.request_stop()
    thread.join(timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS + 1.0)
    # ``os._exit`` skips ``_run``'s ``finally``, so drop the lock first.
    lock.release()
    _LOGGER.info("Stopped server; exiting without interpreter teardown")
    exit_without_interpreter_teardown(0)
    return 0


def _configure_packaged_server(port: int) -> None:
    root = load_packaged_config(
        override_specs=[
            f"server.host={LOOPBACK_HOST}",
            f"server.port={port}",
        ]
    )
    api_config.set_config(root.api)
    bff_config.set_config(root.bff)


def _build_uvicorn_server(port: int) -> uvicorn.Server:
    config = uvicorn.Config(
        create_app,
        host=LOOPBACK_HOST,
        port=port,
        factory=True,
        reload=False,
        log_config=None,
        access_log=True,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    )
    return uvicorn.Server(config)


def _arm_sigusr1_trace_dump() -> None:
    """Arm an all-thread traceback dump on SIGUSR1 when ``TRACE_DUMP_ENV`` is a path.

    Unset leaves the process host unchanged. The file stays open so the signal
    handler can write it without taking the GIL.
    """
    global _trace_dump_file
    path = os.environ.get(TRACE_DUMP_ENV)
    if not path:
        return
    if not hasattr(signal, "SIGUSR1"):
        _LOGGER.warning("%s is set but SIGUSR1 is unavailable on this platform", TRACE_DUMP_ENV)
        return
    _trace_dump_file = open(path, "a", encoding="utf-8")
    faulthandler.register(signal.SIGUSR1, file=_trace_dump_file, all_threads=True)
    _LOGGER.info("SIGUSR1 traceback dump armed at %s", path)


def _run_native_loop(session: ProcessHostSession) -> None:
    system = sys.platform
    if system == "darwin":
        from server.process_host.native_macos import run_appkit_loop

        run_appkit_loop(session)
        return
    if system == "win32":
        from server.process_host.native_windows import run_win32_loop

        run_win32_loop(session)
        return
    raise StartFailure(
        f"{CONSOLE_PACKAGE_DISPLAY_NAME} packaged launch is not supported on {system!r}."
    )
