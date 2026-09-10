"""macOS AppKit event loop: Dock identity, Quit, reopen without a native window."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

_LOGGER = logging.getLogger("server.process_host.native_macos")
_KEEP_DELEGATE: list[object] = []


class MacosHostCallbacks(Protocol):
    def request_stop(self) -> None: ...

    def reopen_browser(self) -> None: ...


def run_appkit_loop(callbacks: MacosHostCallbacks) -> None:
    """Block on NSApplication until Quit / Cmd-Q. Reopen must not create a window."""
    import objc  # type: ignore[import-untyped]
    from AppKit import (  # type: ignore[import-untyped]
        NSApplication,
        NSApplicationActivationPolicyRegular,
        NSApplicationTerminateNow,
    )
    from Foundation import NSObject  # type: ignore[import-untyped]
    from PyObjCTools import AppHelper  # type: ignore[import-untyped]

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
            self._reopen()
            return False

        def applicationShouldTerminate_(self, _app):
            self._stop()
            return NSApplicationTerminateNow

        def applicationShouldTerminateAfterLastWindowClosed_(self, _app):
            return False

        def applicationWillTerminate_(self, _notification):
            self._stop()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = ProcessHostDelegate.alloc().initWithStop_reopen_(
        callbacks.request_stop,
        callbacks.reopen_browser,
    )
    app.setDelegate_(delegate)
    # PyObjC will GC a local delegate while the event loop runs.
    _KEEP_DELEGATE.append(delegate)
    _LOGGER.info("Starting AppKit event loop")
    AppHelper.runEventLoop()
