"""macOS AppKit event loop: Dock identity, Quit, reopen without a native window."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol, TypeVar

from server.package_identity import CONSOLE_PACKAGE_DISPLAY_NAME

_LOGGER = logging.getLogger("server.process_host.native_macos")
_KEEP_DELEGATE: list[object] = []
_T = TypeVar("_T")
_APPKIT_START_TIMEOUT_SECONDS = 15.0

# NSApplicationTerminateCancel. TerminateNow (1) makes terminate: call exit().
TERMINATE_CANCEL = 0


class MacosHostCallbacks(Protocol):
    def request_stop(self) -> None: ...

    def reopen_browser(self) -> None: ...


def handle_macos_quit(
    request_stop: Callable[[], None],
    stop_run_loop: Callable[[], None],
) -> int:
    """Stop uvicorn and NSApp.run(); cancel Cocoa terminate so the host can join.

    ``TerminateNow`` would call C ``exit()`` inside the AppKit callback and skip
    uvicorn's graceful stop. The process host still skips CPython teardown after
    that join (``exit_without_interpreter_teardown``).
    """
    request_stop()
    stop_run_loop()
    return TERMINATE_CANCEL


def handle_macos_reopen(reopen_browser: Callable[[], None]) -> bool:
    """Open the SPA in the browser; return False so AppKit creates no window."""
    reopen_browser()
    return False


def macos_quit_menu_item(
    display_name: str = CONSOLE_PACKAGE_DISPLAY_NAME,
) -> tuple[str, str, str]:
    """Return (title, action, keyEquivalent) for the app-menu Quit item (Cmd-Q)."""
    return (f"Quit {display_name}", "terminate:", "q")


def run_appkit_loop(callbacks: MacosHostCallbacks) -> None:
    """Block on NSApplication.run until Quit / Cmd-Q. Reopen must not create a window."""
    import objc  # type: ignore[import-untyped]
    from AppKit import (  # type: ignore[import-untyped]
        NSApplication,
        NSApplicationActivationPolicyRegular,
    )
    from Foundation import NSObject  # type: ignore[import-untyped]

    class ProcessHostDelegate(NSObject):
        def initWithStop_reopen_(
            self,
            stop: Callable[[], None],
            reopen: Callable[[], None],
        ):
            self = objc.super(ProcessHostDelegate, self).init()
            if self is None:
                return None
            self._stop = stop
            self._reopen = reopen
            return self

        def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _flag):
            return handle_macos_reopen(self._reopen)

        def applicationShouldTerminate_(self, app):
            return handle_macos_quit(self._stop, lambda: _stop_appkit_run_loop(app))

        def applicationShouldTerminateAfterLastWindowClosed_(self, _app):
            return False

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = ProcessHostDelegate.alloc().initWithStop_reopen_(
        callbacks.request_stop,
        callbacks.reopen_browser,
    )
    app.setDelegate_(delegate)
    # PyObjC will GC a local delegate while the event loop runs.
    _KEEP_DELEGATE.append(delegate)
    _install_app_menu(app, CONSOLE_PACKAGE_DISPLAY_NAME)
    _LOGGER.info("Starting AppKit event loop")
    app.run()


class _ProbeHostCallbacks:
    """Process-host callbacks for the occupancy probe: no SPA, no uvicorn."""

    def request_stop(self) -> None:
        return None

    def reopen_browser(self) -> None:
        return None


def run_work_while_appkit_runs(
    work: Callable[[], _T],
    *,
    run_loop: Callable[[MacosHostCallbacks], None] | None = None,
    wait_until_running: Callable[[], None] | None = None,
    stop_loop: Callable[[], None] | None = None,
    own_appkit: Callable[[], None] | None = None,
) -> _T:
    """Run ``work`` on a worker thread while the main thread blocks in AppKit.

    Does not open the SPA or use the console data directory. ``run_loop``
    defaults to ``run_appkit_loop``. Tests inject a fake loop / wait / stop.
    NSApplication is created on this (main) thread before the worker starts so
    a ``sharedApplication`` poll cannot bind the main event queue off-thread.
    """
    result: list[_T] = []
    errors: list[BaseException] = []
    resolved_run = run_loop or run_appkit_loop
    resolved_wait = wait_until_running or _wait_until_appkit_running
    resolved_stop = stop_loop or _stop_shared_appkit_run_loop
    if own_appkit is not None:
        own_appkit()
    elif run_loop is None:
        _own_appkit_on_main_thread()

    def worker() -> None:
        resolved_wait()
        try:
            result.append(work())
        except BaseException as exc:
            errors.append(exc)
        finally:
            resolved_stop()

    thread = threading.Thread(target=worker, name="console-package-probe-appkit")
    thread.start()
    resolved_run(_ProbeHostCallbacks())
    thread.join(timeout=120.0)
    if thread.is_alive():
        raise RuntimeError("AppKit-on probe worker did not finish")
    if errors:
        raise errors[0]
    if not result:
        raise RuntimeError("AppKit-on probe worker produced no result")
    return result[0]


def _own_appkit_on_main_thread() -> None:
    """Create the shared NSApplication on the caller (must be the main thread)."""
    from AppKit import (  # type: ignore[import-untyped]
        NSApplication,
        NSApplicationActivationPolicyRegular,
    )

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)


def _wait_until_appkit_running() -> None:
    from AppKit import NSApplication  # type: ignore[import-untyped]

    deadline = time.monotonic() + _APPKIT_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if bool(NSApplication.sharedApplication().isRunning()):
            return
        time.sleep(0.01)
    raise RuntimeError("NSApplication.run did not start within the probe timeout")


def _stop_shared_appkit_run_loop() -> None:
    from AppKit import NSApplication  # type: ignore[import-untyped]

    _stop_appkit_run_loop(NSApplication.sharedApplication())


def _stop_appkit_run_loop(app: object) -> None:
    from AppKit import NSEvent, NSEventTypeApplicationDefined  # type: ignore[import-untyped]

    app.stop_(app)
    # stop: waits until an event finishes; this wakes run() so it can return.
    dummy = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(  # noqa: E501
        NSEventTypeApplicationDefined,
        (0.0, 0.0),
        0,
        0.0,
        0,
        None,
        0,
        0,
        0,
    )
    if dummy is not None:
        app.postEvent_atStart_(dummy, True)


def _install_app_menu(app: object, display_name: str) -> None:
    from AppKit import NSMenu, NSMenuItem  # type: ignore[import-untyped]

    title, action, key_equivalent = macos_quit_menu_item(display_name)
    menubar = NSMenu.alloc().init()
    app_menu_item = NSMenuItem.alloc().init()
    menubar.addItem_(app_menu_item)
    app_menu = NSMenu.alloc().initWithTitle_(display_name)
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        title,
        action,
        key_equivalent,
    )
    quit_item.setTarget_(app)
    app_menu.addItem_(quit_item)
    app_menu_item.setSubmenu_(app_menu)
    app.setMainMenu_(menubar)
