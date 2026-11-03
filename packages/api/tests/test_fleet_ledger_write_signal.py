"""Host-turn ledger writes signal the shell only while the write attempt runs.

``put_ledger`` takes an int turn. A wildcard scope never reaches this seam;
the persist policy rejects a non-int turn before it writes.
"""

from __future__ import annotations

import gc
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.fleet_table_player_run import (
    FleetLedgerWireProgressTracker,
    FleetPlayerStreamSession,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    _FleetPlayerOrchestratorRun,
    get_fleet_table_stream_scheduler,
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.compute.scope import ComputeScope
from api.storage.base import JSONValue
from api.storage.memory_asset import MemoryAssetBackend


def _drain(session: FleetPlayerStreamSession) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    while not session.event_queue.empty():
        events.append(session.event_queue.get_nowait())
    return events


def _scope(turn: int, player_id: int = 8) -> ComputeScope:
    return ComputeScope(
        analytic_id=ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=turn,
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


class _PutHook:
    """Storage stand-in that runs a hook or raises inside ``put``."""

    def __init__(
        self,
        inner: MemoryAssetBackend,
        *,
        on_put: Callable[[], None] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._inner = inner
        self._on_put = on_put
        self._error = error

    def get(self, key: str) -> JSONValue:
        return self._inner.get(key)

    def put(self, key: str, value: JSONValue) -> None:
        if self._on_put is not None:
            hook = self._on_put
            self._on_put = None
            hook()
        if self._error is not None:
            raise self._error
        self._inner.put(key, value)

    def delete(self, key: str) -> None:
        self._inner.delete(key)

    def list(self, prefix: str) -> list[str]:
        return self._inner.list(prefix)


def _persistence(
    *,
    on_put: Callable[[], None] | None = None,
    error: BaseException | None = None,
) -> FleetSnapshotPersistenceService:
    inner = MemoryAssetBackend(initial={})
    if on_put is None and error is None:
        return FleetSnapshotPersistenceService(inner)
    return FleetSnapshotPersistenceService(_PutHook(inner, on_put=on_put, error=error))


def _persisted(*, player_id: int = 8, final: bool = False) -> PersistedFleetLedger:
    return PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=final,
            prior_ledger_at_n_minus_1=final,
        ),
    )


def _put(
    persistence: FleetSnapshotPersistenceService,
    persisted: PersistedFleetLedger,
    *,
    turn: int,
    player_id: int = 8,
):
    return persistence.put_ledger(
        628580,
        1,
        turn,
        player_id,
        persisted,
        defer_ledger_persisted_notification=True,
    )


def setup_function() -> None:
    reset_fleet_table_stream_scheduler_for_tests()


def teardown_function() -> None:
    reset_fleet_table_stream_scheduler_for_tests()


def test_successful_host_turn_write_ends_the_ledger_write_signal() -> None:
    session = _install_run(host_turn_number=112)
    persistence = _persistence()
    persisted = _persisted(final=True)
    persisted_notices: list[object] = []
    persistence.on_ledger_persisted = persisted_notices.append

    result = _put(persistence, persisted, turn=112)

    assert result.stored.ledger.player_id == persisted.ledger.player_id
    assert persisted_notices == []
    assert result.deferred_notification is not None
    result.deferred_notification()
    assert len(persisted_notices) == 1
    assert persistence.get_ledger(628580, 1, 112, 8) is not None
    assert _drain(session) == [
        {"type": "ledger_write", "writing": True},
        {"type": "ledger_write", "writing": False},
    ]


def test_failed_host_turn_write_ends_the_ledger_write_signal() -> None:
    session = _install_run(host_turn_number=112)
    persistence = _persistence(error=RuntimeError("disk full"))

    with pytest.raises(RuntimeError, match="disk full"):
        _put(persistence, _persisted(), turn=112)

    assert persistence.get_ledger(628580, 1, 112, 8) is None
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

    persistence = _persistence(on_put=_abandon)
    _put(persistence, _persisted(), turn=112)

    assert replacement is not None
    assert _drain(session) == [
        {"type": "ledger_write", "writing": True},
        {"type": "ledger_write", "writing": False},
    ]
    assert _drain(replacement) == []


def test_collected_scheduler_drops_its_ledger_write_listener() -> None:
    turn = SimpleNamespace(settings=SimpleNamespace(turn=112))
    session = FleetPlayerStreamSession(
        player_id=8,
        turn=turn,  # type: ignore[arg-type]
        game_id=628580,
        perspective=1,
    )
    scheduler = FleetTableStreamScheduler()
    scheduler._runs[session.run_id] = _FleetPlayerOrchestratorRun(
        session=session,
        host_turn_number=112,
        progress_tracker=FleetLedgerWireProgressTracker(
            host_turn=turn,  # type: ignore[arg-type]
        ),
        root_scope=_scope(112),
    )
    del scheduler
    gc.collect()

    _put(_persistence(), _persisted(), turn=112)

    assert _drain(session) == []


def test_earlier_walk_hop_does_not_signal_the_shell_tile() -> None:
    session = _install_run(host_turn_number=112)
    persistence = _persistence()

    _put(persistence, _persisted(), turn=111)

    assert persistence.get_ledger(628580, 1, 111, 8) is not None
    assert _drain(session) == []
