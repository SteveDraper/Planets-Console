"""Player-scoped fleet gap-fill and export ensure (#179)."""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics.fleet.chain import (
    _materialize_fleet_ledger_chain_for_player,
    get_or_materialize_fleet_ledger_for_player,
)
from api.analytics.fleet.exports import EXPORT_CATALOG, ensure_fleet_export
from api.analytics.fleet.gap_fill_coordinator import coordinator_for, reset_coordinators
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.errors import FleetMaterializationTimeoutError
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.serialization.turn import turn_info_from_json
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.fleet_player_scoped_gap_fill_helpers import (
    ensure_fleet_export_gap_fill_context,
    install_mid_chain_put_ledger_gate,
    materialize_chain_from_coordinator_module,
    require_turns,
    roster_ids,
    seed_provenance_snapshot,
    two_players_from_turn,
)
from tests.scores_exports_helpers import first_player_id, put_persisted_row
from tests.test_fleet_persistence import (
    _inference_materialization_for_fleet,
    _seed_scores_rows_for_all_players,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _reset_coordinators():
    from api.analytics.military_score_inference.inference_scheduler import (
        reset_inference_row_scheduler_for_tests,
    )

    reset_inference_row_scheduler_for_tests()
    reset_coordinators()
    yield
    reset_inference_row_scheduler_for_tests()
    reset_coordinators()


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_rst = json.load(handle)
        for turn_number in (109, 110, 111, 112):
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


def test_single_player_gap_fill_does_not_materialize_other_players(persistence, load_turn):
    _, turn_112 = require_turns(load_turn, 109, 112)
    player_p, player_q = two_players_from_turn(turn_112)

    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn_112,
        load_turn=load_turn,
    )

    for turn_number in range(110, 113):
        assert persistence.has_ledger(628580, 1, turn_number, player_p)
        assert not persistence.has_ledger(628580, 1, turn_number, player_q)


def test_ensure_fleet_export_scoped_to_player_only(sample_turn, memory_backend):
    ctx, scope, player_id, other_player_id, fleet_persistence = (
        ensure_fleet_export_gap_fill_context(sample_turn, memory_backend)
    )
    ledger_calls: list[int] = []
    original = get_or_materialize_fleet_ledger_for_player

    def tracking_ledger(*args, **kwargs):
        ledger_calls.append(args[3])
        return original(*args, **kwargs)

    with patch(
        "api.analytics.fleet.exports.get_or_materialize_fleet_ledger_for_player",
        side_effect=tracking_ledger,
    ):
        assert ensure_fleet_export(ctx, scope) is True

    assert ledger_calls
    assert set(ledger_calls) == {player_id}
    assert len(ledger_calls) <= 2, (
        f"expected at most two ledger materializations for one-turn gap; got {ledger_calls}"
    )
    assert other_player_id not in ledger_calls
    assert fleet_persistence.has_final_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn,
        player_id,
    )
    assert not fleet_persistence.has_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn,
        other_player_id,
    )


def test_nested_ensure_dedupes_same_player_node(sample_turn, memory_backend):
    """Dependency walk and forward unwind both ensure fleet@T,P once; materialize once."""
    from api.analytics.fleet.compute_services import turn_chain_through

    player_id = first_player_id(sample_turn)
    turn_number = 8
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    host_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=turn_number),
        game=replace(sample_turn.game, turn=turn_number),
    )
    stored_turns = turn_chain_through(host_turn)
    ctx = export_chain_query_context(
        host_turn,
        persistence=inference_persistence,
        stored_turns=stored_turns,
        seed_fleet_prerequisites_for=player_id,
    )
    put_persisted_row(
        inference_persistence,
        host_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seed",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )

    fleet_ensure_calls: list[tuple[int, int | None]] = []
    materialize_calls: list[tuple[int, int]] = []
    original_ensure = ensure_fleet_export
    original_materialize = _materialize_fleet_ledger_chain_for_player

    def tracking_ensure(query_ctx, scope):
        fleet_ensure_calls.append((scope.turn, scope.player_id))
        return original_ensure(query_ctx, scope)

    def counting_materialize(
        persistence_service,
        game_id,
        perspective_id,
        materialize_player_id,
        turn,
        **kwargs,
    ):
        materialize_calls.append((turn.settings.turn, materialize_player_id))
        return original_materialize(
            persistence_service,
            game_id,
            perspective_id,
            materialize_player_id,
            turn,
            **kwargs,
        )

    ctx.export_registry = {
        **ctx.export_registry,
        "fleet": replace(EXPORT_CATALOG, ensure_export=tracking_ensure),
    }

    with (
        patch(
            "api.analytics.fleet.gap_fill_coordinator.ensure_fleet_export",
            side_effect=tracking_ensure,
        ),
        patch(
            "api.analytics.fleet.chain._materialize_fleet_ledger_chain_for_player",
            side_effect=counting_materialize,
        ),
    ):
        result = ctx.query(
            "fleet",
            ["$.players"],
            {"turn": turn_number, "player_id": player_id},
            force_inline_ensure=True,
        )

    assert result.status == "ok"
    target_ensure_calls = [call for call in fleet_ensure_calls if call == (turn_number, player_id)]
    assert len(target_ensure_calls) == 2
    target_materialize_calls = [
        call for call in materialize_calls if call == (turn_number, player_id)
    ]
    assert len(target_materialize_calls) == 1


def test_ensure_fleet_export_does_not_invoke_full_snapshot_materialize(sample_turn, memory_backend):
    ctx, scope, player_id, _, fleet_persistence = ensure_fleet_export_gap_fill_context(
        sample_turn,
        memory_backend,
    )

    def forbid_snapshot(*_args, **_kwargs):
        raise AssertionError("ensure_fleet_export must not call get_or_materialize_fleet_snapshot")

    with patch(
        "api.analytics.fleet.exports.get_or_materialize_fleet_snapshot",
        side_effect=forbid_snapshot,
    ):
        assert ensure_fleet_export(ctx, scope) is True

    assert fleet_persistence.has_final_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn,
        player_id,
    )


def test_per_player_cache_hit_does_not_require_roster_complete(persistence, load_turn):
    from api.analytics.fleet.chain import ensure_fleet_baseline_for_player

    (turn,) = require_turns(load_turn, 111)
    roster = roster_ids(turn)
    player_p = roster[0]
    persistence.put_ledger(
        628580,
        1,
        111,
        player_p,
        PersistedFleetLedger(
            ledger=ensure_fleet_baseline_for_player(628580, 1, turn, player_p),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn,
        load_turn=load_turn,
    )

    assert not persistence.has_ledger(628580, 1, 111, roster[1])


def test_per_player_prior_turn_materializes_while_other_scores_inference_in_progress(
    persistence,
    load_turn,
    memory_backend,
):
    """Incident regression (game 628580 turn 8): fleet 409 while scores stream active.

    Per-player materialization of fleet@(T-1) for one player must succeed without
    requiring all-roster snapshot finality when other players' scores@T inference is
    still in progress. Would raise ConflictError under perspective-batch coordinator
    behavior that waited for full-roster ensure-final before one-player access.
    """
    turn_110, turn_111, turn_112 = require_turns(load_turn, 110, 111, 112)
    player_p, player_q = two_players_from_turn(turn_112)

    seed_provenance_snapshot(persistence, load_turn, from_turn=110)

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()
    # Terminal scores@111 closes turn evidence so fleet@111 is final and may
    # invalidate scores@112. scores@112 for Q stays incomplete (incident shape).
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)

    inference_persistence.put_row(
        628580,
        1,
        112,
        player_p,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="done-for-p",
            solution_count=1,
            is_complete=True,
            solutions=[],
        ),
    )
    inference_persistence.put_row(
        628580,
        1,
        112,
        player_q,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="still-running",
            solution_count=0,
            is_complete=False,
            solutions=[],
        ),
    )

    assert persistence.get_snapshot(628580, 1, 111) is None
    assert not persistence.has_ledger(628580, 1, 111, player_p)
    assert not persistence.has_ledger(628580, 1, 111, player_q)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn_111,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert persistence.has_final_ledger(628580, 1, 111, player_p)
    assert not persistence.has_ledger(628580, 1, 111, player_q)
    snapshot_111 = persistence.get_snapshot(628580, 1, 111)
    assert snapshot_111 is None or player_q not in {
        ledger.player_id for ledger in snapshot_111.players
    }
    assert inference_persistence.get_row(628580, 1, 112, player_p) is None
    assert inference_persistence.get_row(628580, 1, 112, player_q) is not None


def test_per_player_gap_fill_emits_deferred_scores_invalidation_for_player(
    persistence,
    load_turn,
    memory_backend,
):
    turn_110, turn_111, turn_112 = require_turns(load_turn, 110, 111, 112)
    player_p, player_q = two_players_from_turn(turn_112)
    seed_provenance_snapshot(persistence, load_turn, from_turn=110)

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()
    # Terminal scores@111 required for final fleet@111 -> scores@112 invalidation.
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn_111,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert persistence.has_final_ledger(628580, 1, 111, player_p)
    assert inference_persistence.get_row(628580, 1, 112, player_p) is None
    assert inference_persistence.get_row(628580, 1, 112, player_q) is not None


def test_per_player_gap_start_independent(persistence, load_turn):
    turn_109, turn_110, turn_111 = require_turns(load_turn, 109, 110, 111)
    player_p, player_q = two_players_from_turn(turn_111)

    seed_provenance_snapshot(persistence, load_turn, from_turn=109)
    seed_provenance_snapshot(persistence, load_turn, from_turn=110)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_p,
        turn_111,
        load_turn=load_turn,
    )

    assert persistence.has_ledger(628580, 1, 111, player_p)
    assert not persistence.has_ledger(628580, 1, 111, player_q)


def test_compute_fleet_fan_out_materializes_all_players_explicitly(persistence, load_turn):
    from api.analytics.compute_context import invoke_analytic_compute
    from api.analytics.fleet import compute_fleet
    from api.analytics.fleet.compute_services import FleetComputeServices

    turn_109, turn_112 = require_turns(load_turn, 109, 112)
    roster_size = len(roster_ids(turn_112))
    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    fleet_services = FleetComputeServices(
        persistence=persistence,
        game_id=628580,
        perspective=1,
        load_turn=load_turn,
        inference_materialization=None,
    )

    ledger_calls = 0
    original = get_or_materialize_fleet_ledger_for_player

    def counting_ledger(*args, **kwargs):
        nonlocal ledger_calls
        ledger_calls += 1
        return original(*args, **kwargs)

    with patch(
        "api.analytics.fleet.chain.get_or_materialize_fleet_ledger_for_player",
        side_effect=counting_ledger,
    ):
        invoke_analytic_compute(
            compute_fleet,
            turn_112,
            export_services={"fleet": fleet_services},
        )

    assert ledger_calls == roster_size


def test_coordinator_two_threads_same_player_share_one_chain(persistence, load_turn):
    turn_109, turn_111, turn_112 = require_turns(load_turn, 109, 111, 112)
    player_id = roster_ids(turn_112)[0]
    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    materialize_calls = 0
    original_chain = materialize_chain_from_coordinator_module()

    def counting_chain(*args, **kwargs):
        nonlocal materialize_calls
        materialize_calls += 1
        return original_chain(*args, **kwargs)

    results: list[object] = []

    def materialize_to(turn):
        results.append(
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn,
                load_turn=load_turn,
            ),
        )

    with patch(
        "api.analytics.fleet.gap_fill_coordinator._materialize_fleet_ledger_chain_for_player",
        side_effect=counting_chain,
    ):
        leader = threading.Thread(target=materialize_to, args=(turn_111,))
        waiter = threading.Thread(target=materialize_to, args=(turn_112,))
        leader.start()
        waiter.start()
        leader.join(timeout=30)
        waiter.join(timeout=30)

    assert len(results) == 2
    assert materialize_calls == 1


def test_coordinator_same_player_waiters_satisfy_to_max_turn(persistence, load_turn):
    turn_109, turn_111, turn_112 = require_turns(load_turn, 109, 111, 112)
    player_id = roster_ids(turn_112)[0]
    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    leader_ready = threading.Event()
    release_leader = threading.Event()
    coordinator = coordinator_for(persistence, 628580, 1, player_id)
    original_run_leader = coordinator._run_leader_unwind

    def gated_run_leader(inflight, turn, **kwargs):
        leader_ready.set()
        assert release_leader.wait(timeout=5)
        return original_run_leader(inflight, turn, **kwargs)

    with patch.object(coordinator, "_run_leader_unwind", side_effect=gated_run_leader):
        leader = threading.Thread(
            target=lambda: get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_111,
                load_turn=load_turn,
            ),
        )
        waiter = threading.Thread(
            target=lambda: get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_id,
                turn_112,
                load_turn=load_turn,
            ),
        )
        leader.start()
        assert leader_ready.wait(timeout=5)
        waiter.start()
        release_leader.set()
        leader.join(timeout=30)
        waiter.join(timeout=30)

    assert persistence.has_ledger(628580, 1, 111, player_id)
    assert persistence.has_ledger(628580, 1, 112, player_id)


def test_coordinator_different_players_separate_dedupe_keys(persistence, load_turn):
    turn_109, turn_110, turn_111, turn_112 = require_turns(load_turn, 109, 110, 111, 112)
    player_p, player_q = two_players_from_turn(turn_112)
    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    coordinator_p = coordinator_for(persistence, 628580, 1, player_p)
    coordinator_q = coordinator_for(persistence, 628580, 1, player_q)
    assert coordinator_p is not coordinator_q

    leader_p_ready = threading.Event()
    release_p = threading.Event()
    original_p_unwind = coordinator_p._run_leader_unwind

    def gated_p_unwind(inflight, turn, **kwargs):
        leader_p_ready.set()
        assert release_p.wait(timeout=5)
        return original_p_unwind(inflight, turn, **kwargs)

    q_started = threading.Event()
    errors: list[BaseException] = []

    def materialize_q() -> None:
        q_started.set()
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_q,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    def materialize_p() -> None:
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_p,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    with patch.object(coordinator_p, "_run_leader_unwind", side_effect=gated_p_unwind):
        thread_p = threading.Thread(target=materialize_p)
        thread_q = threading.Thread(target=materialize_q)
        thread_p.start()
        assert leader_p_ready.wait(timeout=5)
        thread_q.start()
        assert q_started.wait(timeout=5)
        thread_q.join(timeout=30)
        release_p.set()
        thread_p.join(timeout=30)

    assert not errors, f"thread errors: {errors}"
    assert persistence.has_ledger(628580, 1, 112, player_p)
    assert persistence.has_ledger(628580, 1, 112, player_q)


def test_coordinator_waiter_timeout_per_player(persistence, load_turn):
    turn_109, turn_112 = require_turns(load_turn, 109, 112)
    player_p, player_q = two_players_from_turn(turn_112)
    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    started = threading.Event()
    release = threading.Event()
    original_unwind = coordinator_for(persistence, 628580, 1, player_p)._run_leader_unwind

    def blocking_unwind(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5)
        return original_unwind(*args, **kwargs)

    errors: list[BaseException] = []

    def wait_for_p() -> None:
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_p,
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
            coordinator_for(persistence, 628580, 1, player_p),
            "_run_leader_unwind",
            side_effect=blocking_unwind,
        ),
    ):
        leader = threading.Thread(
            target=lambda: get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_p,
                turn_112,
                load_turn=load_turn,
            ),
        )
        waiter = threading.Thread(target=wait_for_p)
        leader.start()
        assert started.wait(timeout=5)
        waiter.start()
        waiter.join(timeout=5)
        release.set()
        leader.join(timeout=5)

        # Player Q is unaffected by player P's timeout.
        get_or_materialize_fleet_ledger_for_player(
            persistence,
            628580,
            1,
            player_q,
            turn_112,
            load_turn=load_turn,
        )

    assert any(isinstance(error, FleetMaterializationTimeoutError) for error in errors)
    assert persistence.has_ledger(628580, 1, 112, player_q)


def test_forward_unwind_scores_before_fleet_per_player(
    persistence,
    load_turn,
    memory_backend,
):
    """Gap M..N for one player: scores@t,P is ensured before fleet@t,P at each gap turn."""
    from api.analytics.export_context import AnalyticQueryContext

    turn_109, turn_111, turn_112 = require_turns(load_turn, 109, 111, 112)
    player_p = roster_ids(turn_112)[0]

    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    _, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )

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
        from api.analytics.export_dependency_walk import DependencyWalkResult

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
        get_or_materialize_fleet_ledger_for_player(
            persistence,
            628580,
            1,
            player_p,
            turn_112,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
        )

    assert ensure_events
    assert all(player_id == player_p for _, _, player_id in ensure_events), (
        f"ensure calls must be scoped to player {player_p}; events={ensure_events}"
    )

    fleet_turns = [
        turn for analytic_id, turn, _player_id in ensure_events if analytic_id == "fleet"
    ]
    assert fleet_turns
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


def test_invalidation_mid_chain_same_player_waiters_retry_once(persistence, load_turn):
    """P invalidation aborts P's chain and waiters retry; Q's in-flight chain is unaffected."""
    turn_109, turn_112 = require_turns(load_turn, 109, 112)
    player_p, player_q = two_players_from_turn(turn_112)
    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    leader_mid_chain = threading.Event()
    p_waiter_joined = threading.Event()
    q_started = threading.Event()
    release_leader = threading.Event()
    install_mid_chain_put_ledger_gate(
        persistence,
        player_id=player_p,
        turn_number=111,
        leader_mid_chain=leader_mid_chain,
        release_leader=release_leader,
    )

    coordinator_p = coordinator_for(persistence, 628580, 1, player_p)
    coordinator_q = coordinator_for(persistence, 628580, 1, player_q)
    original_chain = materialize_chain_from_coordinator_module()
    original_run_leader_p = coordinator_p._run_leader_unwind

    p_materialize_calls = 0
    q_materialize_calls = 0
    leader_unwind_calls = 0

    def counting_chain(*args, **kwargs):
        nonlocal p_materialize_calls, q_materialize_calls
        materialize_player_id = args[3]
        if materialize_player_id == player_p:
            p_materialize_calls += 1
        elif materialize_player_id == player_q:
            q_materialize_calls += 1
        return original_chain(*args, **kwargs)

    def counting_run_leader_p(
        inflight,
        turn,
        *,
        load_turn,
        inference_materialization,
        query_context,
    ):
        nonlocal leader_unwind_calls
        leader_unwind_calls += 1
        return original_run_leader_p(
            inflight,
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
        )

    p_leader_result: PersistedFleetLedger | None = None
    p_waiter_result: PersistedFleetLedger | None = None
    errors: list[BaseException] = []

    def run_p_leader() -> None:
        nonlocal p_leader_result
        try:
            p_leader_result = get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_p,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    def run_p_waiter() -> None:
        nonlocal p_waiter_result
        assert leader_mid_chain.wait(timeout=5)
        p_waiter_joined.set()
        try:
            p_waiter_result = get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_p,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    def run_q() -> None:
        q_started.set()
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_q,
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
        patch.object(coordinator_p, "_run_leader_unwind", side_effect=counting_run_leader_p),
    ):
        p_leader_thread = threading.Thread(target=run_p_leader)
        p_waiter_thread = threading.Thread(target=run_p_waiter)
        q_thread = threading.Thread(target=run_q)
        p_leader_thread.start()
        p_waiter_thread.start()
        assert leader_mid_chain.wait(timeout=5)
        assert p_waiter_joined.wait(timeout=5)
        q_thread.start()
        assert q_started.wait(timeout=5)
        persistence.invalidate_player_ledgers_from_turn(628580, 1, 111, player_p)
        release_leader.set()
        p_leader_thread.join(timeout=30)
        p_waiter_thread.join(timeout=30)
        q_thread.join(timeout=30)

    assert not errors
    assert p_leader_result is not None
    assert p_waiter_result is not None
    assert p_leader_result.ledger.player_id == player_p
    assert p_waiter_result.ledger.player_id == player_p
    assert persistence.get_ledger(628580, 1, 112, player_p) is not None
    assert persistence.get_ledger(628580, 1, 112, player_q) is not None
    assert leader_unwind_calls == 1, f"expected one P leader unwind, got {leader_unwind_calls}"
    assert p_materialize_calls <= 2, (
        f"expected at most one P invalidation retry, got {p_materialize_calls}"
    )
    assert q_materialize_calls == 1, (
        f"expected one Q materialization chain, got {q_materialize_calls}"
    )
    assert coordinator_p is not coordinator_q


def test_coordinator_q_unaffected_when_p_epoch_bumps_mid_chain(persistence, load_turn):
    """Q leader does not re-enter materialize chain when only P's epoch bumps."""
    turn_109, turn_112 = require_turns(load_turn, 109, 112)
    player_p, player_q = two_players_from_turn(turn_112)
    seed_provenance_snapshot(persistence, load_turn, from_turn=109)

    leader_mid_chain = threading.Event()
    q_started = threading.Event()
    release_leader = threading.Event()
    install_mid_chain_put_ledger_gate(
        persistence,
        player_id=player_p,
        turn_number=111,
        leader_mid_chain=leader_mid_chain,
        release_leader=release_leader,
    )

    coordinator_q = coordinator_for(persistence, 628580, 1, player_q)
    original_chain = materialize_chain_from_coordinator_module()
    original_run_leader_q = coordinator_q._run_leader_unwind

    q_materialize_calls = 0
    q_leader_unwind_calls = 0
    q_epoch_at_start: int | None = None
    errors: list[BaseException] = []

    def counting_chain(*args, **kwargs):
        nonlocal q_materialize_calls
        materialize_player_id = args[3]
        if materialize_player_id == player_q:
            q_materialize_calls += 1
        return original_chain(*args, **kwargs)

    def counting_run_leader_q(
        inflight,
        turn,
        *,
        load_turn,
        inference_materialization,
        query_context,
    ):
        nonlocal q_leader_unwind_calls, q_epoch_at_start
        if q_epoch_at_start is None:
            q_epoch_at_start = coordinator_q.epoch
        q_leader_unwind_calls += 1
        return original_run_leader_q(
            inflight,
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
        )

    def run_p_leader() -> None:
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_p,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            errors.append(exc)

    def run_q() -> None:
        q_started.set()
        try:
            get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_q,
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
        patch.object(coordinator_q, "_run_leader_unwind", side_effect=counting_run_leader_q),
    ):
        p_leader_thread = threading.Thread(target=run_p_leader)
        p_leader_thread.start()
        assert leader_mid_chain.wait(timeout=5)
        q_thread = threading.Thread(target=run_q)
        q_thread.start()
        assert q_started.wait(timeout=5)
        q_epoch_before_invalidation = coordinator_q.epoch
        persistence.invalidate_player_ledgers_from_turn(628580, 1, 111, player_p)
        assert coordinator_q.epoch == q_epoch_before_invalidation
        release_leader.set()
        p_leader_thread.join(timeout=30)
        q_thread.join(timeout=30)

    assert not errors
    assert persistence.get_ledger(628580, 1, 112, player_q) is not None
    assert q_epoch_at_start is not None
    assert coordinator_q.epoch == q_epoch_at_start
    assert q_leader_unwind_calls == 1, f"expected one Q leader unwind, got {q_leader_unwind_calls}"
    assert q_materialize_calls == 1, (
        f"expected one Q materialization chain, got {q_materialize_calls}"
    )
