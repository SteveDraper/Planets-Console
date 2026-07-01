"""Tests for fleet gap-fill coordinator singleflight and forward unwind."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
from api.analytics.fleet.gap_fill_coordinator import coordinator_for, reset_coordinators
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetTurnSnapshot
from api.errors import FleetMaterializationTimeoutError
from api.serialization.turn import turn_info_from_json
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _reset_coordinators():
    reset_coordinators()
    yield
    reset_coordinators()


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        turn_rst = json.load(f)
        backend.put("games/628580/1/turns/111", turn_rst)
        for turn_number in (110, 112):
            turn_data = copy.deepcopy(turn_rst)
            turn_data["settings"]["turn"] = turn_number
            turn_data["game"]["turn"] = turn_number
            backend.put(f"games/628580/1/turns/{turn_number}", turn_data)
    return backend


@pytest.fixture
def persistence(memory_backend):
    return FleetSnapshotPersistenceService(memory_backend)


@pytest.fixture
def load_turn(memory_backend):
    def _load(turn_number: int):
        key = f"games/628580/1/turns/{turn_number}"
        try:
            data = memory_backend.get(key)
        except Exception:
            return None
        if data is None:
            return None
        return turn_info_from_json(data)

    return _load


def test_coordinator_singleflight_satisfies_concurrent_turn_requests(persistence, load_turn):
    from api.analytics.fleet.chain import ensure_fleet_baseline

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_111 = load_turn(111)
    turn_112 = load_turn(112)
    assert turn_111 is not None and turn_112 is not None

    materialize_calls = 0
    original_chain = __import__(
        "api.analytics.fleet.gap_fill_coordinator",
        fromlist=["_materialize_fleet_snapshot_chain"],
    )._materialize_fleet_snapshot_chain

    def counting_chain(*args, **kwargs):
        nonlocal materialize_calls
        materialize_calls += 1
        return original_chain(*args, **kwargs)

    results: dict[int, object] = {}
    errors: dict[int, BaseException] = {}

    def materialize_to(turn_number: int) -> None:
        turn = load_turn(turn_number)
        assert turn is not None
        try:
            results[turn_number] = get_or_materialize_fleet_snapshot(
                persistence,
                628580,
                1,
                turn,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors[turn_number] = exc

    leader_ready = threading.Event()
    release_leader = threading.Event()
    coordinator = coordinator_for(persistence, 628580, 1)
    original_run_leader = coordinator._run_leader_unwind

    def gated_run_leader(
        inflight,
        turn,
        *,
        load_turn,
        inference_materialization,
        query_context,
        materialize_player_id,
    ):
        leader_ready.set()
        assert release_leader.wait(timeout=5)
        return original_run_leader(
            inflight,
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
            materialize_player_id=materialize_player_id,
        )

    with (
        patch(
            "api.analytics.fleet.gap_fill_coordinator._materialize_fleet_snapshot_chain",
            side_effect=counting_chain,
        ),
        patch.object(coordinator, "_run_leader_unwind", side_effect=gated_run_leader),
    ):
        leader_thread = threading.Thread(target=materialize_to, args=(111,))
        waiter_thread = threading.Thread(target=materialize_to, args=(112,))
        leader_thread.start()
        assert leader_ready.wait(timeout=5)
        waiter_thread.start()
        release_leader.set()
        leader_thread.join(timeout=10)
        waiter_thread.join(timeout=10)

    assert not errors
    assert results[111] is not None
    assert results[112] is not None
    assert materialize_calls == 1


def test_coordinator_waiter_times_out_when_leader_never_finishes(persistence, load_turn):
    from api.analytics.fleet.chain import ensure_fleet_baseline

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))
    turn_112 = load_turn(112)
    assert turn_112 is not None

    started = threading.Event()
    release_leader = threading.Event()

    original_unwind = coordinator_for(
        persistence,
        628580,
        1,
    )._run_leader_unwind

    def blocking_unwind(*args, **kwargs):
        started.set()
        assert release_leader.wait(timeout=5)
        return original_unwind(*args, **kwargs)

    errors: list[BaseException] = []

    def wait_for_snapshot() -> None:
        try:
            get_or_materialize_fleet_snapshot(
                persistence,
                628580,
                1,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    with (
        patch(
            "api.analytics.fleet.gap_fill_coordinator.GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC",
            0.2,
        ),
        patch.object(
            coordinator_for(persistence, 628580, 1),
            "_run_leader_unwind",
            side_effect=blocking_unwind,
        ),
    ):
        leader = threading.Thread(
            target=lambda: get_or_materialize_fleet_snapshot(
                persistence,
                628580,
                1,
                turn_112,
                load_turn=load_turn,
            ),
        )
        waiter = threading.Thread(target=wait_for_snapshot)
        leader.start()
        assert started.wait(timeout=5)
        waiter.start()
        waiter.join(timeout=5)
        release_leader.set()
        leader.join(timeout=5)

    assert waiter.is_alive() is False
    assert any(isinstance(error, FleetMaterializationTimeoutError) for error in errors)


def test_forward_unwind_calls_ensure_fleet_export_per_gap_turn(
    persistence,
    load_turn,
    memory_backend,
):
    from tests.test_fleet_persistence import (
        _inference_materialization_for_fleet,
        _put_provenance_final_snapshot,
    )

    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    turn_112 = load_turn(112)
    assert turn_112 is not None
    turn_111 = load_turn(111)
    assert turn_111 is not None
    _, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )

    from api.analytics.export_context import AnalyticQueryContext
    from api.analytics.export_dependency_walk import DependencyWalkResult

    ensure_events: list[tuple[str, int, int | None]] = []
    fleet_exports = __import__(
        "api.analytics.fleet.exports",
        fromlist=["ensure_fleet_export"],
    )
    original_fleet_ensure = fleet_exports.ensure_fleet_export

    def tracking_ensure_declared_dependencies(self, analytic_id, scope):
        walk_outcome = self._walk_export_dependencies(
            analytic_id,
            scope,
            catch_ensure_cycle=False,
        )
        if not isinstance(walk_outcome, DependencyWalkResult):
            return walk_outcome
        for dependency_id, dependency_scope, catalog in walk_outcome.pending_ensure:
            if dependency_id == analytic_id and dependency_scope == scope:
                break
            if catalog.ensure_export is None:
                continue
            ensure_events.append(
                (dependency_id, dependency_scope.turn, dependency_scope.player_id),
            )
            catalog.ensure_export(self, dependency_scope)
        return None

    def tracking_fleet_ensure(query_ctx, scope):
        result = original_fleet_ensure(query_ctx, scope)
        ensure_events.append(("fleet", scope.turn, scope.player_id))
        return result

    with (
        patch(
            "api.analytics.fleet.gap_fill_coordinator.ensure_fleet_export",
            side_effect=tracking_fleet_ensure,
        ),
        patch.object(
            AnalyticQueryContext,
            "ensure_declared_dependencies",
            tracking_ensure_declared_dependencies,
        ),
    ):
        get_or_materialize_fleet_snapshot(
            persistence,
            628580,
            1,
            turn_112,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
        )

    fleet_turns = [
        turn
        for analytic_id, turn, _player_id in ensure_events
        if analytic_id == "fleet"
    ]
    assert fleet_turns
    assert min(fleet_turns) <= 111
    assert max(fleet_turns) >= 111

    gap_turns = range(min(fleet_turns), max(fleet_turns) + 1)
    for event_index, (analytic_id, turn, player_id) in enumerate(ensure_events):
        if analytic_id != "fleet" or turn not in gap_turns:
            continue
        prior_scores = [
            index
            for index, (dependency_id, dependency_turn, dependency_player_id) in enumerate(
                ensure_events[:event_index],
            )
            if dependency_id == "scores"
            and dependency_turn == turn
            and dependency_player_id == player_id
        ]
        assert prior_scores, (
            f"expected scores ensure before fleet ensure at turn {turn} "
            f"for player {player_id}; events={ensure_events}"
        )


def test_gap_fill_forward_unwind_refines_intermediate_turn_build_option_sets(
    persistence,
    load_turn,
    memory_backend,
):
    """Gap M..N: intermediate turn scoreboard placeholders get non-empty buildOptionSets."""
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.turn_roster import iter_turn_players
    from api.serialization.inference_row_persistence import PersistedInferenceRow
    from tests.scores_exports_helpers import ship_build_wire
    from tests.test_fleet_persistence import (
        _inference_materialization_for_fleet,
        _put_provenance_final_snapshot,
        _seed_scores_rows_for_all_players,
    )

    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    turn_111 = load_turn(111)
    turn_112 = load_turn(112)
    assert turn_111 is not None and turn_112 is not None

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)
    for player in iter_turn_players(turn_111):
        if player.id == 8:
            inference_persistence.put_row(
                628580,
                1,
                111,
                player.id,
                PersistedInferenceRow(
                    status=STATUS_EXACT,
                    summary="one cruiser",
                    solution_count=1,
                    is_complete=True,
                    solutions=[
                        {
                            "objectiveValue": 55,
                            "actions": [],
                            "shipBuilds": [
                                ship_build_wire(
                                    combo_id="combo-13",
                                    label="Cruiser",
                                    hull_id=13,
                                    engine_id=9,
                                )
                            ],
                        }
                    ],
                ),
            )
        else:
            inference_persistence.put_row(
                628580,
                1,
                111,
                player.id,
                PersistedInferenceRow(
                    status=STATUS_EXACT,
                    summary=f"cached-{player.id}",
                    solution_count=0,
                    is_complete=True,
                    solutions=[],
                ),
            )

    assert persistence.get_snapshot(628580, 1, 111) is None

    get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_112,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    intermediate = persistence.get_snapshot(628580, 1, 111)
    assert intermediate is not None
    koshling = next(ledger for ledger in intermediate.players if ledger.player_id == 8)
    placeholders = [
        record
        for record in koshling.records
        if any(event.kind == "scoreboard_delta" for event in record.events)
    ]
    assert placeholders
    assert all(len(record.build_option_sets) > 0 for record in placeholders)
    assert placeholders[0].build_option_sets[0].hull_id == 13


def test_coordinator_waiter_retries_with_leader_after_epoch_bump(persistence, load_turn):
    """Waiter blocked on inflight work retries with the leader after invalidation bumps epoch."""
    from api.analytics.fleet.chain import ensure_fleet_baseline

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_112 = load_turn(112)
    assert turn_112 is not None

    leader_mid_chain = threading.Event()
    waiter_joined = threading.Event()
    release_leader = threading.Event()
    original_put_ledger = persistence.put_ledger
    mid_chain_puts = 0

    def hooked_put_ledger(*args, **kwargs):
        nonlocal mid_chain_puts
        turn_number = args[2]
        original_put_ledger(*args, **kwargs)
        if turn_number == 111 and mid_chain_puts == 0:
            mid_chain_puts += 1
            leader_mid_chain.set()
            assert release_leader.wait(timeout=5)

    persistence.put_ledger = hooked_put_ledger  # type: ignore[method-assign]

    leader_result: FleetTurnSnapshot | None = None
    waiter_result: FleetTurnSnapshot | None = None
    errors: list[BaseException] = []

    def run_leader() -> None:
        nonlocal leader_result
        try:
            leader_result = get_or_materialize_fleet_snapshot(
                persistence,
                628580,
                1,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    def run_waiter() -> None:
        nonlocal waiter_result
        assert leader_mid_chain.wait(timeout=5)
        waiter_joined.set()
        try:
            waiter_result = get_or_materialize_fleet_snapshot(
                persistence,
                628580,
                1,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    leader = threading.Thread(target=run_leader)
    waiter = threading.Thread(target=run_waiter)
    leader.start()
    waiter.start()
    assert waiter_joined.wait(timeout=5)
    persistence.invalidate_for_turn_write(628580, 1, 111)
    release_leader.set()
    leader.join(timeout=30)
    waiter.join(timeout=30)

    assert not errors
    assert leader_result is not None
    assert waiter_result is not None
    assert leader_result.turn == 112
    assert waiter_result.turn == 112
    assert persistence.get_snapshot(628580, 1, 112) is not None
