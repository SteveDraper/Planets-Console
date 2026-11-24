"""Run a callback on a dedicated thread when woken, from any context.

A table stream's connect ``finally`` can run while its generator is collected
as cyclic garbage, on whatever thread the collection interrupted. That thread
may already hold the compute orchestrator's non-reentrant lock, so the
``finally`` must not call into the orchestrator. It wakes an ``OffLockWaker``
instead, whose thread runs the work with no lock held.

``wake`` is safe in that context: it reads one attribute and calls
``queue.SimpleQueue.put``, which is reentrant and never blocks. It never runs
the callback inline.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Final

logger = logging.getLogger(__name__)


class _Signal:
    """A message to the waker thread: run the callback, or stop."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return f"<{self._name}>"


_WAKE: Final = _Signal("wake")
_STOP: Final = _Signal("stop")


class OffLockWaker:
    """One daemon thread that runs ``callback`` once per ``wake``.

    Started by ``ensure_started`` from a caller that holds no lock the callback
    takes. Each start gets a fresh queue and thread, so a stop posted to a
    previous thread is never seen by a newer one. A wake while not started,
    including after ``shutdown``, does nothing. A callback that raises is
    logged and the thread waits for the next wake.
    """

    def __init__(self, callback: Callable[[], None], *, thread_name: str) -> None:
        self._callback = callback
        self._thread_name = thread_name
        self._lifecycle_lock = threading.Lock()
        self._signals: queue.SimpleQueue[_Signal] | None = None
        self._thread: threading.Thread | None = None

    def ensure_started(self) -> None:
        """Start the waker thread unless it is already running."""
        with self._lifecycle_lock:
            if self._signals is not None:
                return
            signals: queue.SimpleQueue[_Signal] = queue.SimpleQueue()
            thread = threading.Thread(
                target=self._run,
                args=(signals,),
                name=self._thread_name,
                daemon=True,
            )
            self._signals = signals
            self._thread = thread
            thread.start()

    def wake(self) -> None:
        """Ask the waker thread to run the callback. Reentrant; never blocks."""
        signals = self._signals
        if signals is not None:
            signals.put(_WAKE)

    def shutdown(self, *, timeout: float = 1.0) -> None:
        """Stop the waker thread and wait up to ``timeout`` for it to finish.

        Wakes posted before the stop still run. Called from the callback
        itself, it stops the thread without waiting for it.
        """
        with self._lifecycle_lock:
            signals = self._signals
            thread = self._thread
            self._signals = None
            self._thread = None
        if signals is None or thread is None:
            return
        signals.put(_STOP)
        if thread is not threading.current_thread():
            thread.join(timeout)

    def _run(self, signals: queue.SimpleQueue[_Signal]) -> None:
        while signals.get() is not _STOP:
            try:
                self._callback()
            except Exception:
                logger.exception(
                    "%s callback %r failed; waiting for the next wake",
                    self._thread_name,
                    self._callback,
                )
