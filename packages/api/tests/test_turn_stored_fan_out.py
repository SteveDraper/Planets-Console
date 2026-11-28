"""``TurnStoredFanOut``: invalidate and cancel at once, then wake scores after open root plans.

Every invalidation runs even when one fails; the first failure is raised as
``TurnStoredInvalidationError`` after the wake was handed over. The wake goes
through the orchestrator resolved at each call: inside a root-plan block it is
held until the block exits, and with no orchestrator the stand-in runs it at
once.
"""

from __future__ import annotations

import logging

import pytest
from api.compute import ComputeOrchestrator, build_compute_registry
from api.models.turn_write import TurnWrite
from api.services.turn_stored_fan_out import TurnStoredFanOut, TurnStoredInvalidationError

from tests.compute_orchestrator_fixtures import RecordingPoolSubmitter
from tests.contained_callback_guard import CONTAINMENT_LOGGER

WRITE = TurnWrite(game_id=628580, perspective=1, turn_number=111)


class _InjectedFailure(RuntimeError):
    pass


class _RecordingScores:
    """A scores consumer that records its calls and raises from the named ones."""

    def __init__(self, calls: list[str], *, failing: frozenset[str] = frozenset()) -> None:
        self._calls = calls
        self._failing = failing

    def _record(self, name: str, write: TurnWrite) -> None:
        assert write == WRITE
        self._calls.append(name)
        if name in self._failing:
            raise _InjectedFailure(name)

    def invalidate_for_turn_write(self, write: TurnWrite) -> None:
        self._record("scores delete", write)

    def cancel_for_turn_write(self, write: TurnWrite) -> None:
        self._record("scores cancel", write)

    def wake_for_turn_write(self, write: TurnWrite) -> None:
        self._record("scores wake", write)


def _invalidator(calls: list[str], name: str, *, fails: bool = False):
    def invalidate(write: TurnWrite) -> None:
        assert write == WRITE
        calls.append(name)
        if fails:
            raise _InjectedFailure(name)

    return invalidate


def _orchestrator() -> ComputeOrchestrator:
    return ComputeOrchestrator(
        compute_registry=build_compute_registry(()), pool_submitter=RecordingPoolSubmitter()
    )


def _fan_out(calls: list[str], *, orchestrator=None, failing=frozenset(), failing_invalidators=()):
    return TurnStoredFanOut(
        _RecordingScores(calls, failing=failing),
        (
            _invalidator(calls, "fleet", fails="fleet" in failing_invalidators),
            _invalidator(calls, "homeworld", fails="homeworld" in failing_invalidators),
        ),
        lambda: orchestrator,
    )


def test_invalidations_run_in_order_then_the_wake():
    calls: list[str] = []

    _fan_out(calls).on_turn_stored(WRITE)

    assert calls == ["scores delete", "scores cancel", "fleet", "homeworld", "scores wake"]


def test_the_wake_is_held_until_the_open_root_plan_block_exits():
    calls: list[str] = []
    orchestrator = _orchestrator()
    fan_out = _fan_out(calls, orchestrator=orchestrator)

    with orchestrator.observers.root_plan_block():
        fan_out.on_turn_stored(WRITE)
        assert calls == ["scores delete", "scores cancel", "fleet", "homeworld"]

    assert calls[-1] == "scores wake"


def test_the_orchestrator_is_resolved_at_each_turn_write_never_at_construction():
    resolved: list[str] = []

    def resolve():
        resolved.append("resolved")

    fan_out = TurnStoredFanOut(_RecordingScores([]), (), resolve)
    assert resolved == []

    fan_out.on_turn_stored(WRITE)
    fan_out.on_turn_stored(WRITE)

    assert resolved == ["resolved", "resolved"]


@pytest.mark.allows_contained_callback_errors
@pytest.mark.parametrize("failing", ["scores delete", "scores cancel", "fleet", "homeworld"])
def test_a_failed_invalidation_is_raised_after_every_other_one_and_the_wake(caplog, failing):
    calls: list[str] = []
    fan_out = _fan_out(
        calls,
        failing=frozenset({failing}),
        failing_invalidators=(failing,),
    )

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        with pytest.raises(TurnStoredInvalidationError) as error:
            fan_out.on_turn_stored(WRITE)

    assert calls == ["scores delete", "scores cancel", "fleet", "homeworld", "scores wake"]
    assert error.value.write == WRITE
    assert isinstance(error.value.__cause__, _InjectedFailure)
    assert str(error.value.__cause__) == failing
    assert [record.exc_info[1] for record in caplog.records] == [error.value.__cause__]


@pytest.mark.allows_contained_callback_errors
def test_the_first_of_several_invalidation_failures_is_the_cause(caplog):
    calls: list[str] = []
    fan_out = _fan_out(
        calls,
        failing=frozenset({"scores cancel"}),
        failing_invalidators=("homeworld",),
    )

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        with pytest.raises(TurnStoredInvalidationError) as error:
            fan_out.on_turn_stored(WRITE)

    assert str(error.value.__cause__) == "scores cancel"
    assert [str(record.exc_info[1]) for record in caplog.records] == ["scores cancel", "homeworld"]


@pytest.mark.allows_contained_callback_errors
@pytest.mark.parametrize("has_orchestrator", [False, True])
def test_a_failed_wake_is_contained_and_logged(caplog, has_orchestrator):
    calls: list[str] = []
    orchestrator = _orchestrator() if has_orchestrator else None
    fan_out = _fan_out(calls, orchestrator=orchestrator, failing=frozenset({"scores wake"}))

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        fan_out.on_turn_stored(WRITE)

    assert calls[-1] == "scores wake"
    [record] = caplog.records
    assert str(record.exc_info[1]) == "scores wake"
