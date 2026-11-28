"""Fail a test when a contained callback raises.

``run_contained`` logs a raising callback (an orchestrator post-lock
callback or listener, or a step of a collected fan-out) and keeps going, so
without this guard a broken callback only leaves an ERROR log behind. The
guard attaches its own handler to the containment logger rather than reading
``caplog``: a handler sees records from every thread (pool workers drain
callbacks too), spans fixture setup and teardown as well as the test call,
and does not depend on the level or propagation a test sets for ``caplog``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from api.callback_containment import logger as callback_containment_logger

CONTAINMENT_LOGGER = callback_containment_logger.name

_FAILURE_FORMAT = logging.Formatter("[%(threadName)s] %(message)s")


class _ErrorRecordCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def failing_on_contained_callback_errors() -> Iterator[None]:
    """Fail on exit if a contained callback raised on any thread inside the block."""
    collector = _ErrorRecordCollector()
    callback_containment_logger.addHandler(collector)
    try:
        yield
    finally:
        callback_containment_logger.removeHandler(collector)
    if collector.records:
        failures = "\n\n".join(_FAILURE_FORMAT.format(record) for record in collector.records)
        pytest.fail(
            f"{len(collector.records)} contained callback failure(s) were logged; mark the test "
            f"allows_contained_callback_errors only if it raises on purpose:\n\n{failures}",
            pytrace=False,
        )
