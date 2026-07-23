"""Tests for fleet gap-fill coordinator singleflight and forward unwind."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics.fleet.chain import (
    get_or_materialize_fleet_ledger_for_player,
    get_or_materialize_fleet_snapshot,
)
from api.analytics.fleet.gap_fill_coordinator import coordinator_for, reset_coordinators
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import PersistedFleetLedger
from api.analytics.turn_roster import iter_turn_players
from api.errors import ConflictError, FleetGapFillEpochInvalidated, FleetMaterializationTimeoutError
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


def _first_player_id(turn) -> int:
    return next(iter_turn_players(turn)).id


def test_coordinator_singleflight_satisfies_concurrent_turn_requests(persistence, load_turn):
    from api.analytics.fleet.chain import ensure_fleet_baseline

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_111 = load_turn(111)
    turn_112 = load_turn(112)
    assert turn_111 is not None and turn_112 is not None
    player_id = _first_player_id(turn_111)

    materialize_calls = 0
    original_chain = __import__(
        "api.analytics.fleet.gap_fill_coordinator",
        fromlist=["_materialize_fleet_ledger_chain_for_player"],
    )._materialize_fleet_ledger_chain_for_player

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
            results[turn_number] = get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors[turn_number] = exc

    leader_ready = threading.Event()
    release_leader = threading.Event()
    coordinator = coordinator_for(persistence, 628580, 1, player_id)
    original_run_leader = coordinator._run_leader_unwind

    def gated_run_leader(
        inflight,
        turn,
        *,
        load_turn,
        inference_materialization,
        query_context,
    ):
        leader_ready.set()
        assert release_leader.wait(timeout=5)
        return original_run_leader(
            inflight,
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
        )

    with (
        patch(
            "api.analytics.fleet.gap_fill_coordinator._materialize_fleet_ledger_chain_for_player",
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
    player_id = _first_player_id(turn_112)

    started = threading.Event()
    release_leader = threading.Event()

    original_unwind = coordinator_for(
        persistence,
        628580,
        1,
        player_id,
    )._run_leader_unwind

    def blocking_unwind(*args, **kwargs):
        started.set()
        assert release_leader.wait(timeout=5)
        return original_unwind(*args, **kwargs)

    errors: list[BaseException] = []

    def wait_for_ledger() -> None:
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
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
            coordinator_for(persistence, 628580, 1, player_id),
            "_run_leader_unwind",
            side_effect=blocking_unwind,
        ),
    ):
        leader = threading.Thread(
            target=lambda: get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_112,
                load_turn=load_turn,
            ),
        )
        waiter = threading.Thread(target=wait_for_ledger)
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
        turn for analytic_id, turn, _player_id in ensure_events if analytic_id == "fleet"
    ]
    assert fleet_turns
    assert min(fleet_turns) <= 111
    assert max(fleet_turns) >= 111

    gap_turns = range(min(fleet_turns), max(fleet_turns) + 1)
    for event_index, (analytic_id, turn, player_id) in enumerate(ensure_events):
        if analytic_id != "fleet" or turn not in gap_turns:
            continue
        prior_same_turn_scores = [
            index
            for index, (dependency_id, dependency_turn, dependency_player_id) in enumerate(
                ensure_events[:event_index],
            )
            if dependency_id == "scores"
            and dependency_turn == turn
            and dependency_player_id == player_id
        ]
        assert not prior_same_turn_scores, (
            f"fleet ensure at turn {turn} for player {player_id} must not require "
            f"same-turn scores ensure; events={ensure_events}"
        )


def test_forward_unwind_emits_once_per_leg_when_chain_materializes(
    persistence,
    load_turn,
    memory_backend,
):
    """Export unwind must not double-emit leg progress when chain materializes."""
    from api.analytics.fleet.chain import emit_gap_fill_leg_progress

    from tests.test_fleet_persistence import (
        _inference_materialization_for_fleet,
        _put_provenance_final_snapshot,
        _seed_scores_rows_for_all_players,
    )

    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    turn_112 = load_turn(112)
    assert turn_112 is not None
    turn_111 = load_turn(111)
    assert turn_111 is not None
    player_id = _first_player_id(turn_112)
    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    emitted_turns: list[int] = []
    original_emit = emit_gap_fill_leg_progress

    def tracking_emit(persisted: PersistedFleetLedger, materialize_turn: int) -> None:
        emitted_turns.append(materialize_turn)
        original_emit(persisted, materialize_turn)

    with patch(
        "api.analytics.fleet.chain.emit_gap_fill_leg_progress",
        side_effect=tracking_emit,
    ):
        get_or_materialize_fleet_ledger_for_player(
            persistence,
            628580,
            1,
            player_id,
            turn_112,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
        )

    gap_turns = {turn for turn in emitted_turns if 111 <= turn <= 112}
    assert gap_turns, f"expected gap leg progress emissions, got {emitted_turns}"
    assert len(emitted_turns) == len(set(emitted_turns)), (
        f"duplicate leg progress emissions: {emitted_turns}"
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


def test_gap_fill_with_inference_never_uses_legacy_chain_path(
    persistence,
    load_turn,
    memory_backend,
):
    """Inference gap-fill must use forward unwind, not gather-only legacy chain."""
    from tests.test_fleet_persistence import (
        _inference_materialization_for_fleet,
        _put_provenance_final_snapshot,
        _seed_scores_rows_for_all_players,
    )

    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    turn_112 = load_turn(112)
    assert turn_112 is not None
    turn_111 = load_turn(111)
    assert turn_111 is not None
    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    from api.analytics.fleet.gap_fill_coordinator import FleetGapFillCoordinator

    original_forward_unwind = FleetGapFillCoordinator._forward_unwind_via_export_ensure
    forward_unwind_calls = 0

    def tracking_forward_unwind(self, *args, **kwargs):
        nonlocal forward_unwind_calls
        forward_unwind_calls += 1
        return original_forward_unwind(self, *args, **kwargs)

    with (
        patch(
            "api.analytics.fleet.gap_fill_coordinator._materialize_fleet_ledger_chain_for_player",
            side_effect=AssertionError(
                "legacy chain path must not run when inference materialization is set",
            ),
        ),
        patch.object(
            FleetGapFillCoordinator,
            "_forward_unwind_via_export_ensure",
            tracking_forward_unwind,
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

    assert forward_unwind_calls >= 1


def test_gap_fill_with_inference_fails_when_query_context_unresolved(
    persistence,
    load_turn,
    memory_backend,
):
    """Gap-fill with inference must not silently fall back when query context is missing."""
    from tests.test_fleet_persistence import (
        _inference_materialization_for_fleet,
        _put_provenance_final_snapshot,
    )

    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    turn_112 = load_turn(112)
    assert turn_112 is not None
    _, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )

    with (
        patch(
            "api.analytics.fleet.gap_fill_coordinator._resolve_query_context",
            return_value=None,
        ),
        pytest.raises(ConflictError, match="requires query context"),
    ):
        get_or_materialize_fleet_snapshot(
            persistence,
            628580,
            1,
            turn_112,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
        )


def test_coordinator_waiter_retries_with_leader_after_epoch_bump(persistence, load_turn):
    """Mid-chain invalidation aborts once; external re-queue completes after epoch settles."""
    from api.analytics.fleet.chain import ensure_fleet_baseline

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_112 = load_turn(112)
    assert turn_112 is not None
    player_id = _first_player_id(turn_112)

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

    errors: list[BaseException] = []

    def run_leader() -> None:
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    def run_waiter() -> None:
        assert leader_mid_chain.wait(timeout=5)
        waiter_joined.set()
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
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

    assert errors
    assert all(isinstance(exc, FleetGapFillEpochInvalidated) for exc in errors)

    # External re-queue after invalidation settles (orchestrator / ensure pattern).
    persistence.put_ledger = original_put_ledger  # type: ignore[method-assign]
    result = get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_id,
        turn_112,
        load_turn=load_turn,
    )
    assert result.ledger.player_id == player_id
    assert persistence.get_ledger(628580, 1, 112, player_id) is not None


def test_coordinator_invalidation_mid_chain_with_waiters_does_not_storm(
    persistence,
    load_turn,
):
    """Invalidation mid-chain aborts the leg once -- no sync rematerialization spin."""
    from api.analytics.fleet.chain import ensure_fleet_baseline

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_112 = load_turn(112)
    assert turn_112 is not None
    player_id = _first_player_id(turn_112)

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

    coordinator = coordinator_for(persistence, 628580, 1, player_id)
    original_chain = __import__(
        "api.analytics.fleet.gap_fill_coordinator",
        fromlist=["_materialize_fleet_ledger_chain_for_player"],
    )._materialize_fleet_ledger_chain_for_player
    original_run_leader = coordinator._run_leader_unwind

    materialize_calls = 0
    leader_unwind_calls = 0

    def counting_chain(*args, **kwargs):
        nonlocal materialize_calls
        materialize_calls += 1
        return original_chain(*args, **kwargs)

    def counting_run_leader(
        inflight,
        turn,
        *,
        load_turn,
        inference_materialization,
        query_context,
    ):
        nonlocal leader_unwind_calls
        leader_unwind_calls += 1
        return original_run_leader(
            inflight,
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
        )

    errors: list[BaseException] = []

    def run_leader() -> None:
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    def run_waiter() -> None:
        assert leader_mid_chain.wait(timeout=5)
        waiter_joined.set()
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    with (
        patch(
            "api.analytics.fleet.gap_fill_coordinator._materialize_fleet_ledger_chain_for_player",
            side_effect=counting_chain,
        ),
        patch.object(coordinator, "_run_leader_unwind", side_effect=counting_run_leader),
    ):
        leader_thread = threading.Thread(target=run_leader)
        waiter_thread = threading.Thread(target=run_waiter)
        leader_thread.start()
        waiter_thread.start()
        assert waiter_joined.wait(timeout=5)
        persistence.invalidate_for_turn_write(628580, 1, 111)
        release_leader.set()
        leader_thread.join(timeout=30)
        waiter_thread.join(timeout=30)

    assert errors
    assert all(isinstance(exc, FleetGapFillEpochInvalidated) for exc in errors)
    assert leader_unwind_calls == 1, f"expected one leader unwind, got {leader_unwind_calls}"
    assert materialize_calls == 1, (
        f"expected a single chain attempt (no sync spin), got {materialize_calls}"
    )

    persistence.put_ledger = original_put_ledger  # type: ignore[method-assign]
    result = get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_id,
        turn_112,
        load_turn=load_turn,
    )
    assert result.ledger.player_id == player_id
    assert persistence.get_ledger(628580, 1, 112, player_id) is not None


def test_joiner_on_progress_receives_incremental_events_during_inflight_gap_fill(
    persistence,
    load_turn,
):
    """Joiner with on_progress receives leg events while waiting on inflight gap-fill."""
    from api.analytics.fleet.chain import ensure_fleet_baseline

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_112 = load_turn(112)
    assert turn_112 is not None
    player_id = _first_player_id(turn_112)

    leader_ready = threading.Event()
    release_leader = threading.Event()
    progress_turns: list[int] = []
    progress_lock = threading.Lock()
    errors: list[BaseException] = []

    coordinator = coordinator_for(persistence, 628580, 1, player_id)
    original_run_leader = coordinator._run_leader_unwind

    def gated_run_leader(
        inflight,
        turn,
        *,
        load_turn,
        inference_materialization,
        query_context,
    ):
        leader_ready.set()
        assert release_leader.wait(timeout=5)
        return original_run_leader(
            inflight,
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
        )

    def joiner_on_progress(
        _persisted: PersistedFleetLedger,
        materialize_turn: int,
    ) -> None:
        with progress_lock:
            progress_turns.append(materialize_turn)

    def run_leader() -> None:
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    def run_joiner() -> None:
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_112,
                load_turn=load_turn,
                on_progress=joiner_on_progress,
            )
        except BaseException as exc:
            errors.append(exc)

    with patch.object(coordinator, "_run_leader_unwind", side_effect=gated_run_leader):
        leader_thread = threading.Thread(target=run_leader)
        joiner_thread = threading.Thread(target=run_joiner)
        leader_thread.start()
        assert leader_ready.wait(timeout=5)
        joiner_thread.start()
        release_leader.set()
        leader_thread.join(timeout=30)
        joiner_thread.join(timeout=30)

    assert not errors
    assert len(progress_turns) >= 2
    assert progress_turns == sorted(progress_turns)
    assert min(progress_turns) <= 111
    assert max(progress_turns) >= 112


def test_result_for_request_returns_non_final_ledger_when_result_cleared(
    persistence,
    load_turn,
):
    """Completed cycle with cleared result_ledger must still return a non-final write.

    Phase C leaves many ledgers non-final until scores turn-evidence closes. Leaders
    return those via ``result_ledger``; waiters that lose that pointer (extended
    re-lead clears it) must not raise ``completed without a cache hit`` when the
    ledger for the requested turn is present.
    """
    from api.analytics.fleet.gap_fill_coordinator import _InflightMaterialization
    from api.analytics.fleet.types import (
        FleetAcquisitionLedger,
        FleetMaterializationProvenance,
    )

    turn_111 = load_turn(111)
    assert turn_111 is not None
    player_id = _first_player_id(turn_111)
    non_final = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=False,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    persistence.put_ledger(628580, 1, 111, player_id, non_final)
    assert non_final.provenance.is_final is False

    coordinator = coordinator_for(persistence, 628580, 1, player_id)
    inflight = _InflightMaterialization(
        target_turn=111,
        generation=coordinator.epoch,
        load_turn=load_turn,
        inference_materialization=None,
        query_context=None,
    )
    inflight.event.set()
    inflight.result_ledger = None

    result = coordinator._result_for_request(inflight, 111, turn_111)
    assert result.ledger.player_id == player_id
    assert result.provenance.is_final is False


def test_gap_fill_aborts_when_ledger_cleared_after_coherence(persistence, load_turn):
    """Concurrent scores evidence invalidation can delete fleet after coherence exits.

    ``on_row_persisted`` clears fleet ledgers from the host turn. When that races after
    gap-fill leaves coherence, the leg aborts with ``FleetGapFillEpochInvalidated`` so
    orchestrator / ensure can re-queue -- it does not sync-rematerialize in-leg.
    """
    from api.analytics.fleet import gap_fill_coordinator as gap_fill_mod
    from api.analytics.fleet.chain import ensure_fleet_baseline

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_111 = load_turn(111)
    assert turn_111 is not None
    player_id = _first_player_id(turn_111)

    original_emit = gap_fill_mod.emit_deferred_fleet_ledger_notifications
    clear_count = 0

    def clear_target_ledger_then_emit(*args, **kwargs):
        nonlocal clear_count
        if clear_count == 0:
            clear_count += 1
            persistence.delete_ledger(628580, 1, 111, player_id)
        return original_emit(*args, **kwargs)

    with patch.object(
        gap_fill_mod,
        "emit_deferred_fleet_ledger_notifications",
        side_effect=clear_target_ledger_then_emit,
    ):
        with pytest.raises(FleetGapFillEpochInvalidated, match="produced no ledger"):
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_111,
                load_turn=load_turn,
            )

    assert clear_count == 1

    # External re-queue after the race settles.
    result = get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_id,
        turn_111,
        load_turn=load_turn,
    )
    assert result.ledger.player_id == player_id
    assert persistence.get_ledger(628580, 1, 111, player_id) is not None
