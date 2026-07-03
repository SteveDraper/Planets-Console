"""Player-scoped fleet gap-fill and export ensure (#179)."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.fleet.chain import get_or_materialize_fleet_ledger_for_player
from api.analytics.fleet.exports import ensure_fleet_export
from api.analytics.fleet.gap_fill_coordinator import coordinator_for, reset_coordinators
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.turn_roster import iter_turn_players
from api.errors import FleetMaterializationTimeoutError
from api.serialization.turn import turn_info_from_json
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.test_fleet_persistence import _put_provenance_final_snapshot

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


def _roster_ids(turn) -> list[int]:
    return [player.id for player in iter_turn_players(turn)]


def test_single_player_gap_fill_does_not_materialize_other_players(persistence, load_turn):
    turn_109 = load_turn(109)
    turn_112 = load_turn(112)
    assert turn_109 is not None and turn_112 is not None
    roster = _roster_ids(turn_112)
    assert len(roster) > 1
    player_p, player_q = roster[0], roster[1]

    _put_provenance_final_snapshot(persistence, 628580, 1, turn_109)

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
    from api.analytics.fleet.compute_services import FleetComputeServices, turn_chain_through
    from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
    from api.services.inference_row_persistence_service import InferenceRowPersistenceService

    from tests.scores_exports_helpers import GAME_ID, first_player_id, perspective

    player_id = first_player_id(sample_turn)
    other_player_id = sample_turn.scores[1].ownerid
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    fleet_persistence = FleetSnapshotPersistenceService(memory_backend)
    ctx = export_chain_query_context(sample_turn, persistence=inference_persistence)
    fleet_services = ctx.export_services["fleet"]
    ctx.export_services["fleet"] = FleetComputeServices(
        persistence=fleet_persistence,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        load_turn=lambda turn_number: turn_chain_through(sample_turn).get(turn_number),
        inference_materialization=fleet_services.inference_materialization,
    )
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
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
        ensure_fleet_export(ctx, scope)

    assert ledger_calls
    assert all(call_player_id == player_id for call_player_id in ledger_calls)
    assert other_player_id not in ledger_calls


def test_ensure_fleet_export_does_not_invoke_full_snapshot_materialize(sample_turn, memory_backend):
    from api.analytics.fleet.compute_services import FleetComputeServices, turn_chain_through
    from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
    from api.services.inference_row_persistence_service import InferenceRowPersistenceService

    from tests.scores_exports_helpers import GAME_ID, first_player_id, perspective

    player_id = first_player_id(sample_turn)
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    fleet_persistence = FleetSnapshotPersistenceService(memory_backend)
    ctx = export_chain_query_context(sample_turn, persistence=inference_persistence)
    fleet_services = ctx.export_services["fleet"]
    ctx.export_services["fleet"] = FleetComputeServices(
        persistence=fleet_persistence,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        load_turn=lambda turn_number: turn_chain_through(sample_turn).get(turn_number),
        inference_materialization=fleet_services.inference_materialization,
    )
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )

    def forbid_snapshot(*_args, **_kwargs):
        raise AssertionError("ensure_fleet_export must not call get_or_materialize_fleet_snapshot")

    with patch(
        "api.analytics.fleet.exports.get_or_materialize_fleet_snapshot",
        side_effect=forbid_snapshot,
    ):
        ensure_fleet_export(ctx, scope)


def test_per_player_cache_hit_does_not_require_roster_complete(persistence, load_turn):
    from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
    from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger

    turn = load_turn(111)
    assert turn is not None
    roster = _roster_ids(turn)
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


def test_per_player_gap_start_independent(persistence, load_turn):
    turn_109 = load_turn(109)
    turn_110 = load_turn(110)
    turn_111 = load_turn(111)
    assert turn_109 is not None and turn_110 is not None and turn_111 is not None
    roster = _roster_ids(turn_111)
    player_p, player_q = roster[0], roster[1]

    _put_provenance_final_snapshot(persistence, 628580, 1, turn_109)
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

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

    turn_109 = load_turn(109)
    turn_112 = load_turn(112)
    assert turn_109 is not None and turn_112 is not None
    roster_size = len(_roster_ids(turn_112))
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_109)

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
    turn_109 = load_turn(109)
    turn_111 = load_turn(111)
    turn_112 = load_turn(112)
    assert turn_109 is not None and turn_111 is not None and turn_112 is not None
    player_id = _roster_ids(turn_112)[0]
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_109)

    materialize_calls = 0
    original_chain = __import__(
        "api.analytics.fleet.gap_fill_coordinator",
        fromlist=["_materialize_fleet_ledger_chain_for_player"],
    )._materialize_fleet_ledger_chain_for_player

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
    turn_109 = load_turn(109)
    turn_111 = load_turn(111)
    turn_112 = load_turn(112)
    assert turn_109 is not None and turn_111 is not None and turn_112 is not None
    player_id = _roster_ids(turn_112)[0]
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_109)

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
    turn_109 = load_turn(109)
    turn_112 = load_turn(112)
    assert turn_109 is not None and turn_112 is not None
    roster = _roster_ids(turn_112)
    player_p, player_q = roster[0], roster[1]
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_109)

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

    def materialize_q() -> None:
        q_started.set()
        get_or_materialize_fleet_ledger_for_player(
            persistence,
            628580,
            1,
            player_q,
            turn_112,
            load_turn=load_turn,
        )

    with patch.object(coordinator_p, "_run_leader_unwind", side_effect=gated_p_unwind):
        thread_p = threading.Thread(
            target=lambda: get_or_materialize_fleet_ledger_for_player(
                persistence,
                628580,
                1,
                player_p,
                turn_112,
                load_turn=load_turn,
            ),
        )
        thread_q = threading.Thread(target=materialize_q)
        thread_p.start()
        assert leader_p_ready.wait(timeout=5)
        thread_q.start()
        assert q_started.wait(timeout=5)
        release_p.set()
        thread_p.join(timeout=30)
        thread_q.join(timeout=30)

    assert persistence.has_ledger(628580, 1, 112, player_p)
    assert persistence.has_ledger(628580, 1, 112, player_q)


def test_coordinator_waiter_timeout_per_player(persistence, load_turn):
    turn_109 = load_turn(109)
    turn_112 = load_turn(112)
    assert turn_109 is not None and turn_112 is not None
    player_p, player_q = _roster_ids(turn_112)[:2]
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_109)

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
