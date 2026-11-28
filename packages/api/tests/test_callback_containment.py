"""``run_contained`` and ``FailureCollector`` contain an ``Exception``; an interrupt propagates."""

from __future__ import annotations

import logging

import pytest
from api.callback_containment import FailureCollector, run_contained

from tests.contained_callback_guard import CONTAINMENT_LOGGER


class _CallbackFailed(RuntimeError):
    pass


def _raise_callback_failure() -> None:
    raise _CallbackFailed("callback failed")


def _containment_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == CONTAINMENT_LOGGER]


def test_run_contained_returns_none_when_the_callback_succeeds(caplog):
    ran: list[str] = []

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        error = run_contained(lambda: ran.append("ran"), "Post-lock callback")

    assert error is None
    assert ran == ["ran"]
    assert _containment_records(caplog) == []


@pytest.mark.allows_contained_callback_errors
def test_run_contained_returns_and_logs_the_exception_with_its_label(caplog):
    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        error = run_contained(_raise_callback_failure, "Fleet ledger bump")

    assert isinstance(error, _CallbackFailed)
    [record] = _containment_records(caplog)
    assert "Fleet ledger bump" in record.getMessage()
    assert "_raise_callback_failure" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[1] is error


def test_run_contained_lets_an_interrupt_propagate(caplog):
    def interrupt() -> None:
        raise KeyboardInterrupt

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        with pytest.raises(KeyboardInterrupt):
            run_contained(interrupt, "Post-lock callback")

    assert _containment_records(caplog) == []


def test_a_collector_with_no_failures_has_no_first_error():
    collector = FailureCollector()

    collector.run(lambda: None, "Post-lock callback")

    assert collector.first_error is None


@pytest.mark.allows_contained_callback_errors
def test_a_collector_runs_every_callback_logs_each_failure_and_keeps_the_first(caplog):
    first = _CallbackFailed("first")
    second = _CallbackFailed("second")
    ran: list[str] = []

    def raise_first() -> None:
        ran.append("first")
        raise first

    def raise_second() -> None:
        ran.append("second")
        raise second

    collector = FailureCollector()
    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        collector.run(raise_first, "Post-lock callback")
        collector.run(lambda: ran.append("between"), "Post-lock callback")
        collector.run(raise_second, "Post-lock callback")

    assert ran == ["first", "between", "second"]
    assert collector.first_error is first
    assert [record.exc_info[1] for record in _containment_records(caplog)] == [first, second]


def test_a_collector_lets_an_interrupt_propagate():
    def interrupt() -> None:
        raise KeyboardInterrupt

    collector = FailureCollector()

    with pytest.raises(KeyboardInterrupt):
        collector.run(interrupt, "Post-lock callback")

    assert collector.first_error is None
