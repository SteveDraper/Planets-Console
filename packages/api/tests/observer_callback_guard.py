"""Fail a test when an orchestrator observer callback raises.

The orchestrator observers log a raising callback (a post-lock callback, or a
listener they notify) and keep going, so without this guard a broken listener
only leaves an ERROR log behind. The
guard attaches its own handler to the observers logger rather than reading
``caplog``: a handler sees records from every thread (pool workers drain
callbacks too), spans fixture setup and teardown as well as the test call,
and does not depend on the level or propagation a test sets for ``caplog``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from api.compute.orchestrator_observers import logger as orchestrator_observers_logger

_FAILURE_FORMAT = logging.Formatter("[%(threadName)s] %(message)s")


class _ErrorRecordCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def failing_on_observer_callback_errors() -> Iterator[None]:
    """Fail on exit if an observer callback raised on any thread inside the block."""
    collector = _ErrorRecordCollector()
    orchestrator_observers_logger.addHandler(collector)
    try:
        yield
    finally:
        orchestrator_observers_logger.removeHandler(collector)
    if collector.records:
        failures = "\n\n".join(_FAILURE_FORMAT.format(record) for record in collector.records)
        pytest.fail(
            f"{len(collector.records)} observer callback failure(s) were logged; mark the test "
            f"allows_observer_callback_errors only if it raises on purpose:\n\n{failures}",
            pytrace=False,
        )
