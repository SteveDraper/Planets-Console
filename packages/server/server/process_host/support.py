"""Support log file and native start-failure dialog."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from server.package_identity import CONSOLE_PACKAGE_DISPLAY_NAME

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "process-host.log"

_LOGGER = logging.getLogger("server.process_host")


class StartFailure(RuntimeError):
    """Packaged launch failed; the process host should show a dialog and exit."""


def configure_support_logging(data_dir: Path) -> Path:
    """Log to ``{console data directory}/logs/process-host.log``. Return the path."""
    log_dir = data_dir / LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / LOG_FILE_NAME
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    _LOGGER.info("Process host logging to %s", log_path)
    return log_path


def show_start_failure(
    message: str,
    *,
    display: Callable[[str], None] | None = None,
) -> None:
    """Show a native dialog for a start failure. ``display`` is the test seam."""
    _LOGGER.error("Start failure: %s", message)
    if display is not None:
        display(message)
        return
    if sys.platform == "darwin":
        _show_macos_dialog(message)
        return
    if sys.platform == "win32":
        _show_windows_dialog(message)
        return
    _LOGGER.error("No native start-failure dialog on this platform")


def _show_macos_dialog(message: str) -> None:
    script = (
        f"display dialog {_osascript_string(message)} "
        f"with title {_osascript_string(CONSOLE_PACKAGE_DISPLAY_NAME)} "
        'buttons {"OK"} default button "OK" with icon stop'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except OSError:
        _LOGGER.exception("Failed to show macOS start-failure dialog")


def _show_windows_dialog(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            CONSOLE_PACKAGE_DISPLAY_NAME,
            0x10,  # MB_ICONERROR
        )
    except OSError:
        _LOGGER.exception("Failed to show Windows start-failure dialog")


def _osascript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
