"""Integration tests for fleet table stream invalidation and in-place reschedule."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_services import (
    FleetComputeServices,
    turn_chain_through,
)
from api.analytics.fleet.fleet_table_stream_registry import (
    controller_for_scope,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_rows import iter_fleet_table_stream_events
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend
from api.transport.fleet_table_stream import fleet_complete_event

from tests.table_stream_lock_helpers import assert_stream_lock_not_held

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        backend.put("games/628580/1/turns/111", json.load(handle))
    return backend


def _install_workerless_scheduler(monkeypatch: pytest.MonkeyPatch) -> FleetTableStreamScheduler:
    from api.analytics.military_score_inference.inference_scheduler import (
        reset_inference_row_scheduler_for_tests,
    )
    from api.compute.pools import reset_compute_worker_pool_for_tests
    from api.compute.runtime import reset_orchestrators_for_tests

    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=1)
    reset_inference_row_scheduler_for_tests()
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler()

    def _get_scheduler() -> FleetTableStreamScheduler:
        return scheduler

    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_rows.get_fleet_table_stream_scheduler",
        _get_scheduler,
    )
    return scheduler


def _stream_scope(sample_turn) -> FleetTableStreamScope:
    return FleetTableStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def _end_open_fleet_table_stream(
    scope: FleetTableStreamScope,
    scheduler: FleetTableStreamScheduler,
) -> None:
    controller = controller_for_scope(scope)
    if controller is not None:
        controller.end_stream(scheduler)


def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def _run_ids_for_players(
    scheduler: FleetTableStreamScheduler,
    player_ids: tuple[int, ...],
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for run in scheduler._runs.values():
        session = run.session
        if session.player_id in player_ids:
            mapping[session.player_id] = session.run_id
    return mapping


def _seed_cached_ledgers(
    persistence: FleetSnapshotPersistenceService,
    sample_turn,
    *,
    turn_number: int,
    player_ids: tuple[int, ...],
) -> None:
    for player_id in player_ids:
        persistence.put_ledger(
            628580,
            1,
            turn_number,
            player_id,
            PersistedFleetLedger(
                ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
                provenance=FleetMaterializationProvenance(
                    turn_evidence_at_n=True,
                    prior_ledger_at_n_minus_1=True,
                ),
            ),
        )


def test_all_cached_replay_keeps_stream_open_for_evidence_invalidation_integration(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """All-cached replay: evidence invalidation reschedules on the open stream."""
    from api.analytics.fleet.held_solutions import (
        FleetInferenceMaterialization,
        FleetInferenceSupport,
    )
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.scores.export_services import ScoresExportContext
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    from tests.scores_exports_helpers import put_persisted_row

    reset_fleet_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    scores_services = ScoresExportContext(persistence=inference_persistence)
    for player_id in player_ids:
        put_persisted_row(
            inference_persistence,
            sample_turn,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary="seeded for fleet stream invalidation",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
            host_turn=turn_number,
        )

    stored_turns = turn_chain_through(sample_turn)

    def load_turn(turn: int):
        return stored_turns.get(turn)

    services = FleetComputeServices(
        persistence=FleetSnapshotPersistenceService(memory_backend),
        game_id=628580,
        perspective=1,
        load_turn=load_turn,
        inference_materialization=FleetInferenceMaterialization(
            inference=FleetInferenceSupport(scores_services=scores_services),
            load_turn=load_turn,
        ),
    )
    fleet_persistence = services.persistence
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=fleet_persistence,
    )
    for player_id in player_ids:
        fleet_persistence.put_ledger(
            628580,
            1,
            turn_number - 1,
            player_id,
            PersistedFleetLedger(
                ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
                provenance=FleetMaterializationProvenance(
                    turn_evidence_at_n=True,
                    prior_ledger_at_n_minus_1=True,
                ),
            ),
        )
        put_persisted_row(
            inference_persistence,
            sample_turn,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary="seeded for fleet stream invalidation prior turn",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
            host_turn=turn_number - 1,
        )
    _seed_cached_ledgers(
        fleet_persistence,
        sample_turn,
        turn_number=turn_number,
        player_ids=player_ids,
    )

    stream = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=fleet_persistence,
        scheduler=scheduler,
    )
    events: list[dict[str, object]] = []
    stream_closed = threading.Event()
    scope = _stream_scope(sample_turn)

    def consume_stream() -> None:
        try:
            for event in stream:
                events.append(event)
        finally:
            stream.close()
            stream_closed.set()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()

    _wait_until(
        lambda: sum(1 for event in events if event.get("type") == "complete") >= len(player_ids)
    )
    assert len(scheduler._runs) == 0
    assert not stream_closed.is_set()
    assert controller_for_scope(scope) is not None

    target_player_id, other_player_id = player_ids
    invalidation.on_inference_evidence_updated(628580, 1, turn_number, target_player_id)

    _wait_until(lambda: target_player_id in _run_ids_for_players(scheduler, player_ids))
    assert other_player_id not in _run_ids_for_players(scheduler, (other_player_id,))
    assert fleet_persistence.get_ledger(628580, 1, turn_number, target_player_id) is None

    rescheduled_run = scheduler._runs[_run_ids_for_players(scheduler, player_ids)[target_player_id]]
    rescheduled_run.session.event_queue.put(
        fleet_complete_event(
            is_final=True,
            summary="after evidence invalidation on cached row",
        )
    )
    controller = controller_for_scope(scope)
    if controller is not None:
        controller.wake_multiplex.set()

    _wait_until(
        lambda: any(
            event.get("type") == "complete"
            and event.get("playerId") == target_player_id
            and event.get("summary") == "after evidence invalidation on cached row"
            for event in events
        )
    )
    cached_other_events = [
        event
        for event in events
        if event.get("type") == "complete"
        and event.get("playerId") == other_player_id
        and event.get("summary") == "Fleet ledger loaded from cache."
    ]
    assert len(cached_other_events) == 1

    _end_open_fleet_table_stream(scope, scheduler)
    thread.join(timeout=2.0)


def test_evidence_invalidation_reschedules_player_on_open_stream_integration(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Integration: invalidation while iter_fleet_table_stream_events multiplex is active."""
    from api.analytics.fleet.held_solutions import (
        FleetInferenceMaterialization,
        FleetInferenceSupport,
    )
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.scores.export_services import ScoresExportContext
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    from tests.scores_exports_helpers import put_persisted_row

    reset_fleet_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    scores_services = ScoresExportContext(persistence=inference_persistence)
    for player_id in player_ids:
        put_persisted_row(
            inference_persistence,
            sample_turn,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary="seeded for fleet stream invalidation",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
            host_turn=turn_number,
        )

    stored_turns = turn_chain_through(sample_turn)

    def load_turn(turn: int):
        return stored_turns.get(turn)

    services = FleetComputeServices(
        persistence=FleetSnapshotPersistenceService(memory_backend),
        game_id=628580,
        perspective=1,
        load_turn=load_turn,
        inference_materialization=FleetInferenceMaterialization(
            inference=FleetInferenceSupport(scores_services=scores_services),
            load_turn=load_turn,
        ),
    )
    fleet_persistence = services.persistence
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=fleet_persistence,
    )
    for player_id in player_ids:
        fleet_persistence.put_ledger(
            628580,
            1,
            turn_number - 1,
            player_id,
            PersistedFleetLedger(
                ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
                provenance=FleetMaterializationProvenance(
                    turn_evidence_at_n=True,
                    prior_ledger_at_n_minus_1=True,
                ),
            ),
        )
        put_persisted_row(
            inference_persistence,
            sample_turn,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary="seeded for fleet stream invalidation prior turn",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
            host_turn=turn_number - 1,
        )
    _seed_cached_ledgers(
        fleet_persistence,
        sample_turn,
        turn_number=turn_number,
        player_ids=player_ids,
    )

    stream = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=fleet_persistence,
        scheduler=scheduler,
    )

    def consume_stream() -> None:
        try:
            for _event in stream:
                pass
        finally:
            stream.close()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()
    _wait_until(
        lambda: (
            controller_for_scope(_stream_scope(sample_turn)) is not None
            and len(scheduler._runs) == 0
        )
    )

    target_player_id, other_player_id = player_ids
    before = _run_ids_for_players(scheduler, player_ids)
    assert before == {}

    invalidation.on_inference_evidence_updated(628580, 1, turn_number, target_player_id)

    _wait_until(lambda: target_player_id in _run_ids_for_players(scheduler, player_ids))
    after = _run_ids_for_players(scheduler, player_ids)
    assert other_player_id not in after
    assert fleet_persistence.get_ledger(628580, 1, turn_number, target_player_id) is None

    _end_open_fleet_table_stream(_stream_scope(sample_turn), scheduler)
    thread.join(timeout=2.0)


def test_scores_evidence_invalidation_rematerializes_orchestrator_completed_fleet(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Scores evidence update must rematerialize a fleet node already complete on the DAG.

    Game 628580 t8 pl10: fleet@N completed after scores materialize (no solutions yet).
    Later scores tier_solve persisted exact solutions and invalidated the fleet ledger, but
    reschedule attached to the stale ``complete`` orchestrator node without ``force_fresh``,
    so unreined placeholders never got option sets.
    """
    from api.analytics.fleet.held_solutions import (
        FleetInferenceMaterialization,
        FleetInferenceSupport,
    )
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.scores.export_services import ScoresExportContext
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    from tests.scores_exports_helpers import put_persisted_row

    reset_fleet_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_id = sample_turn.scores[0].ownerid
    player_ids = (player_id,)
    turn_number = sample_turn.settings.turn
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    scores_services = ScoresExportContext(persistence=inference_persistence)
    put_persisted_row(
        inference_persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seeded host turn",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        host_turn=turn_number,
    )
    put_persisted_row(
        inference_persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seeded prior turn",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        host_turn=turn_number - 1,
    )

    stored_turns = turn_chain_through(sample_turn)

    def load_turn(turn: int):
        return stored_turns.get(turn)

    services = FleetComputeServices(
        persistence=FleetSnapshotPersistenceService(memory_backend),
        game_id=628580,
        perspective=1,
        load_turn=load_turn,
        inference_materialization=FleetInferenceMaterialization(
            inference=FleetInferenceSupport(scores_services=scores_services),
            load_turn=load_turn,
        ),
    )
    fleet_persistence = services.persistence
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=fleet_persistence,
    )
    fleet_persistence.put_ledger(
        628580,
        1,
        turn_number - 1,
        player_id,
        PersistedFleetLedger(
            ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )

    events: list[dict[str, object]] = []
    stream = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=fleet_persistence,
    )

    def consume_stream() -> None:
        try:
            for event in stream:
                events.append(event)
        finally:
            stream.close()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()

    _wait_until(
        lambda: fleet_persistence.get_ledger(628580, 1, turn_number, player_id) is not None,
        timeout_seconds=5.0,
    )
    _wait_until(
        lambda: any(
            event.get("type") == "complete" and event.get("playerId") == player_id
            for event in events
        ),
        timeout_seconds=5.0,
    )
    first_ledger = fleet_persistence.get_ledger(628580, 1, turn_number, player_id)
    assert first_ledger is not None

    scope = _stream_scope(sample_turn)
    controller = controller_for_scope(scope)
    assert controller is not None
    binding = next(iter(scheduler._stream_bindings.values()))
    fleet_scope = next(
        node.scope
        for node in binding.orchestrator.nodes.values()
        if node.scope.analytic_id == "fleet"
        and node.scope.player_id == player_id
        and node.scope.turn == turn_number
    )
    assert binding.orchestrator.nodes[fleet_scope].state == "complete"

    invalidation.on_inference_evidence_updated(628580, 1, turn_number, player_id)
    assert fleet_persistence.get_ledger(628580, 1, turn_number, player_id) is None

    # Rematerialize must replace the stale complete DAG node (force_fresh), not attach.
    _wait_until(
        lambda: fleet_persistence.get_ledger(628580, 1, turn_number, player_id) is not None,
        timeout_seconds=5.0,
    )
    rematerialized = fleet_persistence.get_ledger(628580, 1, turn_number, player_id)
    assert rematerialized is not None
    assert binding.orchestrator.nodes[fleet_scope].state == "complete"

    _end_open_fleet_table_stream(scope, scheduler)
    thread.join(timeout=2.0)


def test_reschedule_player_does_not_deadlock_when_schedule_reenters_invalidation(
    sample_turn,
    monkeypatch,
    memory_backend,
    request,
):
    """Schedule under stream_lock must not re-enter reschedule via invalidation.

    Production hang (game 680224): ``reschedule_player`` held ``stream_lock`` across
    ``register_admitted_schedule`` → ``schedule_fleet_player_run`` → orchestrator
    submit/persist. Scores persist then called ``on_inference_evidence_updated`` →
    ``reschedule_fleet_table_player`` → ``reschedule_player``, which blocked forever
    on the same non-reentrant lock (0% CPU; turn-6 workers stuck; turn-8 waiting_deps).
    """
    from api.analytics.fleet.compute_services import (
        FleetComputeServices,
        build_ephemeral_fleet_compute_services,
    )
    from api.analytics.fleet.fleet_table_player_run import (
        FleetPlayerStreamSession,
        ScheduledFleetPlayer,
    )
    from api.analytics.fleet.fleet_table_stream_controller import FleetTableStreamController
    from api.analytics.fleet.fleet_table_stream_rows import SchedulePlayerAdmission
    from api.compute.pools import reset_compute_worker_pool_for_tests
    from api.compute.runtime import reset_orchestrators_for_tests

    reset_fleet_table_stream_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    scheduler = FleetTableStreamScheduler()
    persistence = FleetSnapshotPersistenceService(memory_backend)
    ephemeral = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    fleet_services = FleetComputeServices(
        persistence=persistence,
        game_id=628580,
        perspective=1,
        load_turn=ephemeral.load_turn,
        inference_materialization=ephemeral.inference_materialization,
    )
    player_id = sample_turn.scores[0].ownerid
    scope = _stream_scope(sample_turn)
    stream_token = scheduler.begin_scope(scope)
    controller = FleetTableStreamController(
        scope=scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(player_id,),
        scheduler=scheduler,
        fleet_services=fleet_services,
        persistence=persistence,
    )
    controller.attach()

    def cleanup() -> None:
        controller.end_stream(scheduler)
        reset_fleet_table_stream_registry_for_tests()
        reset_orchestrators_for_tests()
        reset_compute_worker_pool_for_tests(worker_count=1)
        reset_fleet_table_stream_scheduler_for_tests()

    request.addfinalizer(cleanup)

    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_controller.resolve_player_stream_admission",
        lambda *_args, **_kwargs: SchedulePlayerAdmission(),
    )

    nest_depth = {"n": 0}

    def schedule_that_reenters_invalidation(
        _scheduler,
        *,
        turn,
        player_id: int,
        game_id: int,
        perspective: int,
        fleet_services,
        persistence,
        stream_token: str | None = None,
    ) -> ScheduledFleetPlayer:
        del _scheduler, fleet_services, persistence, stream_token
        nest_depth["n"] += 1
        if nest_depth["n"] == 1:
            # Same-thread re-entry fingerprint: scores persist invalidation while
            # outer reschedule still holds stream_lock (before the lock-order fix).
            assert_stream_lock_not_held(
                controller.stream_lock,
                message=(
                    "reschedule_player deadlocked (schedule re-entered stream_lock "
                    "via scores→fleet invalidation)"
                ),
            )
            from api.analytics.fleet.fleet_table_stream_registry import (
                reschedule_fleet_table_player,
            )

            assert reschedule_fleet_table_player(scope, player_id) is True
        session = FleetPlayerStreamSession(
            player_id=player_id,
            turn=turn,
            game_id=game_id,
            perspective=perspective,
        )
        return ScheduledFleetPlayer(player_id=player_id, session=session)

    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_controller.schedule_fleet_player_run",
        schedule_that_reenters_invalidation,
    )

    assert controller.reschedule_player(player_id) is True
    assert nest_depth["n"] >= 2
    assert player_id in controller.scheduled_rows
