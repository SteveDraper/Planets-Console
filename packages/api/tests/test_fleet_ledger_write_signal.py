"""Host-turn ledger writes signal the shell only while the write attempt runs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from api.analytics.fleet.compute_orchestration import _put_ledger_signaled
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.fleet_table_player_run import (
    FleetLedgerWireProgressTracker,
    FleetPlayerStreamSession,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    _FleetPlayerOrchestratorRun,
    get_fleet_table_stream_scheduler,
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.fleet.types import FleetAcquisitionLedger, PersistedFleetLedger
from api.compute.scope import ComputeScope


def _drain(session: FleetPlayerStreamSession) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    while not session.event_queue.empty():
        events.append(session.event_queue.get_nowait())
    return events


def _scope(turn: int | str, player_id: int = 8) -> ComputeScope:
    return ComputeScope(
        analytic_id=ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=turn,  # type: ignore[arg-type]
        player_id=player_id,
    )


def _install_run(
    *,
    host_turn_number: int,
    player_id: int = 8,
) -> FleetPlayerStreamSession:
    turn = SimpleNamespace(settings=SimpleNamespace(turn=host_turn_number))
    session = FleetPlayerStreamSession(
        player_id=player_id,
        turn=turn,  # type: ignore[arg-type]
        game_id=628580,
        perspective=1,
    )
    scheduler = get_fleet_table_stream_scheduler()
    scheduler._runs[session.run_id] = _FleetPlayerOrchestratorRun(
        session=session,
        host_turn_number=host_turn_number,
        progress_tracker=FleetLedgerWireProgressTracker(
            host_turn=turn,  # type: ignore[arg-type]
        ),
        root_scope=_scope(host_turn_number, player_id),
    )
    return session


class _LedgerPersistence:
    def __init__(self, *, error: BaseException | None = None, on_put=None) -> None:
        self.error = error
        self.on_put = on_put
        self.calls = 0
        self.deferred = None

    def put_ledger(
        self,
        game_id: int,
        perspective: int,
        turn: int,
        player_id: int,
        persisted: PersistedFleetLedger,
        *,
        defer_ledger_persisted_notification: bool = False,
    ):
        del game_id, perspective, turn, player_id
        self.calls += 1
        self.deferred = defer_ledger_persisted_notification
        if self.on_put is not None:
            self.on_put()
        if self.error is not None:
            raise self.error
        return SimpleNamespace(stored=persisted)


def _persisted(player_id: int = 8) -> PersistedFleetLedger:
    return PersistedFleetLedger(ledger=FleetAcquisitionLedger(player_id=player_id))


def setup_function() -> None:
    reset_fleet_table_stream_scheduler_for_tests()


def teardown_function() -> None:
    reset_fleet_table_stream_scheduler_for_tests()


def test_successful_host_turn_write_ends_the_ledger_write_signal() -> None:
    session = _install_run(host_turn_number=112)
    persistence = _LedgerPersistence()
    persisted = _persisted()

    result = _put_ledger_signaled(_scope(112), persistence, persisted)

    assert result.stored is persisted
    assert persistence.calls == 1
    assert persistence.deferred is True
    assert _drain(session) == [
        {"type": "ledger_write", "writing": True},
        {"type": "ledger_write", "writing": False},
    ]


def test_failed_host_turn_write_ends_the_ledger_write_signal() -> None:
    session = _install_run(host_turn_number=112)
    persistence = _LedgerPersistence(error=RuntimeError("disk full"))

    with pytest.raises(RuntimeError, match="disk full"):
        _put_ledger_signaled(_scope(112), persistence, _persisted())

    assert _drain(session) == [
        {"type": "ledger_write", "writing": True},
        {"type": "ledger_write", "writing": False},
    ]


def test_abandoned_host_turn_write_ends_on_the_session_that_started_it() -> None:
    """Cancel removes the run during put_ledger and does not raise.

    The off signal still belongs to the session that saw the write start.
    A replacement run for the same shell turn does not receive it.
    """
    session = _install_run(host_turn_number=112)
    scheduler = get_fleet_table_stream_scheduler()
    replacement: FleetPlayerStreamSession | None = None

    def _abandon() -> None:
        nonlocal replacement
        scheduler._runs.pop(session.run_id, None)
        replacement = _install_run(host_turn_number=112)

    persistence = _LedgerPersistence(on_put=_abandon)
    _put_ledger_signaled(_scope(112), persistence, _persisted())

    assert replacement is not None
    assert _drain(session) == [
        {"type": "ledger_write", "writing": True},
        {"type": "ledger_write", "writing": False},
    ]
    assert _drain(replacement) == []


def test_earlier_walk_hop_does_not_signal_the_shell_tile() -> None:
    session = _install_run(host_turn_number=112)
    persistence = _LedgerPersistence()

    _put_ledger_signaled(_scope(111), persistence, _persisted())

    assert persistence.calls == 1
    assert _drain(session) == []


def test_non_int_turn_does_not_signal_the_shell_tile() -> None:
    session = _install_run(host_turn_number=112)
    persistence = _LedgerPersistence()

    _put_ledger_signaled(_scope("*"), persistence, _persisted())

    assert persistence.calls == 1
    assert _drain(session) == []
