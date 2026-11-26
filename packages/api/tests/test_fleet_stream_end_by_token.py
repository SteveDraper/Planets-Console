"""A fleet stream ends by its token; the scheduler shuts down cleanly."""

from __future__ import annotations

from types import SimpleNamespace

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_player_run import (
    FleetLedgerWireProgressTracker,
    FleetPlayerStreamSession,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    _FleetPlayerOrchestratorRun,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import _ledger_write_listeners
from api.compute.scope import ComputeScope

GAME_ID = 628580
PERSPECTIVE = 1
TURN = 111


def _stream_scope() -> FleetTableStreamScope:
    return FleetTableStreamScope(game_id=GAME_ID, perspective=PERSPECTIVE, turn_number=TURN)


def _install_run(
    scheduler: FleetTableStreamScheduler, player_id: int, accepted: list[str] | None = None
) -> FleetPlayerStreamSession:
    turn = SimpleNamespace(settings=SimpleNamespace(turn=TURN))
    session = FleetPlayerStreamSession(
        player_id=player_id,
        turn=turn,  # type: ignore[arg-type]
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
    )
    scheduler._runs[session.run_id] = _FleetPlayerOrchestratorRun(
        session=session,
        host_turn_number=TURN,
        progress_tracker=FleetLedgerWireProgressTracker(host_turn=turn),  # type: ignore[arg-type]
        root_scope=ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=GAME_ID,
            perspective=PERSPECTIVE,
            turn=TURN - 1,
            player_id=player_id,
        ),
    )
    record = accepted if accepted is not None else []
    scheduler._pending_accepts.register(session.run_id, lambda: record.append(session.run_id))
    return session


def test_an_owner_end_cancels_every_run_and_discards_its_accepts() -> None:
    scheduler = FleetTableStreamScheduler()
    try:
        scope = _stream_scope()
        token = scheduler.begin_scope(scope)
        accepted: list[str] = []
        sessions = [_install_run(scheduler, player_id, accepted) for player_id in (3, 8)]

        scheduler.end_table_stream(scope, token)

        assert scheduler._runs == {}
        assert all(session.cancel_token.is_cancelled() for session in sessions)
        assert not scheduler.owns_table_stream(token)
        for session in sessions:
            scheduler._pending_accepts.accept(session.run_id)
        assert accepted == []
    finally:
        scheduler.shutdown()


def test_a_replaced_streams_end_leaves_the_current_streams_runs() -> None:
    scheduler = FleetTableStreamScheduler()
    try:
        scope = _stream_scope()
        replaced = scheduler.begin_scope(scope)
        current = scheduler.begin_scope(scope)
        session = _install_run(scheduler, 3)

        scheduler.end_table_stream(scope, replaced)

        assert session.run_id in scheduler._runs
        assert not session.cancel_token.is_cancelled()
        assert scheduler.owns_table_stream(current)
    finally:
        scheduler.shutdown()


def test_shutdown_unregisters_the_ledger_listener_and_is_idempotent() -> None:
    scheduler = FleetTableStreamScheduler()
    listeners_with_scheduler = len(_ledger_write_listeners)

    scheduler.shutdown()
    scheduler.shutdown()

    assert len(_ledger_write_listeners) == listeners_with_scheduler - 1
    assert scheduler._orchestrator_attachment.registered_orchestrator() is None
