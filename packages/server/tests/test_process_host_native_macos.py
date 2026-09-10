"""macOS Quit maps to uvicorn stop + run-loop return, not Cocoa terminate/exit."""

from __future__ import annotations

from server.package_identity import CONSOLE_PACKAGE_DISPLAY_NAME
from server.process_host.native_macos import (
    TERMINATE_CANCEL,
    handle_macos_quit,
    handle_macos_reopen,
    macos_quit_menu_item,
)

# NSApplicationTerminateNow -- terminate: calls exit() if shouldTerminate returns this.
_TERMINATE_NOW = 1


def test_macos_quit_cancels_cocoa_terminate_and_stops_run_loop():
    stops: list[str] = []

    reply = handle_macos_quit(
        request_stop=lambda: stops.append("uvicorn"),
        stop_run_loop=lambda: stops.append("run_loop"),
    )

    assert stops == ["uvicorn", "run_loop"]
    assert reply == TERMINATE_CANCEL
    assert reply != _TERMINATE_NOW


def test_macos_reopen_opens_browser_without_native_window():
    reopened: list[bool] = []

    creates_window = handle_macos_reopen(lambda: reopened.append(True))

    assert reopened == [True]
    assert creates_window is False


def test_macos_quit_menu_item_is_cmd_q_terminate():
    title, action, key_equivalent = macos_quit_menu_item()

    assert title == f"Quit {CONSOLE_PACKAGE_DISPLAY_NAME}"
    assert action == "terminate:"
    assert key_equivalent == "q"
