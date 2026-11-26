"""Run posted work on a dedicated thread, posting from any context.

A table stream's connect ``finally`` can run while its generator is finalized:
by the cycle collector, or when its last reference drops, on whatever thread
that happens. That thread may already hold any lock the stream's teardown
takes, so the ``finally`` must not take one. It posts the teardown to an
``OffLockRunner`` instead, whose own thread runs it with no lock held.

``post`` is safe in that context: it calls ``queue.SimpleQueue.put`` on a
queue that lives as long as the runner, which is reentrant and never blocks.
Work posted while no runner thread is alive (before the first start, or after
the thread died) stays queued and runs once a thread is started.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class _Stop:
    """Tells the runner thread to exit."""


class _DrainMarker:
    """Set once every item posted before it has run."""

    def __init__(self) -> None:
        self.reached = threading.Event()


_Item = Callable[[], None] | _Stop | _DrainMarker


class OffLockRunner:
    """One daemon thread that runs posted work in post order.

    An item that raises an ``Exception`` is logged and the next item runs. A
    ``BaseException`` ends the thread and is logged once; the item it
    interrupted is lost, the rest of the queue is kept, and the next
    ``ensure_started`` starts a thread that resumes it.
    """

    def __init__(self, *, thread_name: str) -> None:
        self._thread_name = thread_name
        self._items: queue.SimpleQueue[_Item] = queue.SimpleQueue()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def post(self, work: Callable[[], None]) -> None:
        """Queue ``work`` for the runner thread. Reentrant; never blocks."""
        self._items.put(work)

    def ensure_started(self) -> None:
        """Start the runner thread unless one is alive. Call holding no lock posted work takes."""
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            thread = threading.Thread(target=self._run, name=self._thread_name, daemon=True)
            self._thread = thread
            thread.start()

    def drain(self, timeout: float) -> bool:
        """Wait up to ``timeout`` for every item posted so far to run.

        Returns whether they all ran. With no live runner thread it returns at
        once: True when nothing is queued. Called on the runner thread itself
        it returns False at once, since that thread cannot wait on its own queue.
        """
        thread = self._thread
        if thread is threading.current_thread():
            return False
        if thread is None or not thread.is_alive():
            return self._items.empty()
        marker = _DrainMarker()
        self._items.put(marker)
        return marker.reached.wait(timeout)

    def shutdown(self, *, timeout: float = 1.0) -> None:
        """Run the queued work, then stop the runner thread and wait for it.

        Does nothing when no runner thread is alive. Called from posted work,
        it stops the thread after the current item without waiting for it.
        """
        with self._lifecycle_lock:
            thread = self._thread
            self._thread = None
            if thread is None or not thread.is_alive():
                return
            if thread is threading.current_thread():
                self._items.put(_Stop())
                return
            marker = _DrainMarker()
            self._items.put(marker)
            marker.reached.wait(timeout)
            self._items.put(_Stop())
            thread.join(timeout)

    def _run(self) -> None:
        try:
            while True:
                item = self._items.get()
                if isinstance(item, _Stop):
                    return
                if isinstance(item, _DrainMarker):
                    item.reached.set()
                    continue
                try:
                    item()
                except Exception:
                    logger.exception(
                        "%s work %r failed; running the next item", self._thread_name, item
                    )
        except BaseException:
            logger.exception(
                "%s thread stopped unexpectedly; the next ensure_started resumes the queue",
                self._thread_name,
            )
