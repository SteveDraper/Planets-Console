"""macOS AppKit event loop: Dock identity, Quit, reopen without a native window."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from server.package_identity import CONSOLE_PACKAGE_DISPLAY_NAME

_LOGGER = logging.getLogger("server.process_host.native_macos")
_KEEP_DELEGATE: list[object] = []

# NSApplicationTerminateCancel. TerminateNow (1) makes terminate: call exit().
TERMINATE_CANCEL = 0


class MacosHostCallbacks(Protocol):
    def request_stop(self) -> None: ...

    def reopen_browser(self) -> None: ...


def handle_macos_quit(
    request_stop: Callable[[], None],
    stop_run_loop: Callable[[], None],
) -> int:
    """Stop uvicorn and NSApp.run(); cancel Cocoa terminate so Python can join."""
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
