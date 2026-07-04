"""Fleet ledger persist -> scores inference invalidation coupling (#182)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
from api.analytics.fleet.gap_fill_coordinator import reset_coordinators
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.serialization.turn import turn_info_from_json
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.storage.memory_asset import MemoryAssetBackend

from tests.test_fleet_persistence import (
    _inference_materialization_for_fleet,
    _put_provenance_final_snapshot,
    _seed_scores_rows_for_all_players,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _reset_fleet_gap_fill_coordinators():
    reset_coordinators()
    yield
    reset_coordinators()


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_rst = json.load(handle)
        backend.put("games/628580/1/turns/111", turn_rst)
        turn_110 = copy.deepcopy(turn_rst)
        turn_110["settings"]["turn"] = 110
        turn_110["game"]["turn"] = 110
        backend.put("games/628580/1/turns/110", turn_110)
        turn_112 = copy.deepcopy(turn_rst)
        turn_112["settings"]["turn"] = 112
        turn_112["game"]["turn"] = 112
        backend.put("games/628580/1/turns/112", turn_112)
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


def test_gap_fill_defers_ledger_notify_until_chain_completes(
    persistence,
    load_turn,
    memory_backend,
):
    """Per-player put_ledger during gap-fill must not notify; flush runs after the chain."""
    from api.analytics.turn_roster import iter_turn_players

    turn_111 = load_turn(111)
    assert turn_111 is not None
    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)

    callback_events: list[tuple[int, int]] = []
    persistence.on_ledger_persisted = lambda _g, _p, turn_number, player_id: callback_events.append(
        (turn_number, player_id)
    )

    put_ledger_calls = 0
    original_put_ledger = persistence.put_ledger

    def counting_put_ledger(*args, **kwargs):
        nonlocal put_ledger_calls
        put_ledger_calls += 1
        return original_put_ledger(*args, **kwargs)

    persistence.put_ledger = counting_put_ledger  # type: ignore[method-assign]

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_111,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert snapshot.turn == 111
    roster_size = len(list(iter_turn_players(turn_111)))
    assert roster_size > 1
    assert put_ledger_calls >= roster_size
    assert len(callback_events) == roster_size
    assert all(turn_number == 111 for turn_number, _ in callback_events)


def test_gap_fill_emits_deferred_scores_invalidation_after_chain_completes(
    persistence,
    load_turn,
    memory_backend,
):
    """After gap-fill, newly complete fleet@(T-1) invalidates scores@T (not mid-chain)."""
    from api.analytics.turn_roster import iter_turn_players

    inference_persistence, inference_materialization = _inference_materialization_for_fleet(
        memory_backend,
        load_turn,
    )
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()

    turn_112 = load_turn(112)
    assert turn_112 is not None
    turn_111 = load_turn(111)
    assert turn_111 is not None
    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)
    _seed_scores_rows_for_all_players(inference_persistence, turn_111)
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_112,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    assert snapshot.turn == 112
    for player in iter_turn_players(turn_112):
        assert inference_persistence.get_row(628580, 1, 112, player.id) is None


def test_fleet_ledger_persisted_invalidates_scores_row_for_player_only(
    persistence,
    load_turn,
    memory_backend,
    monkeypatch,
):
    from api.analytics.turn_roster import iter_turn_players

    inference_persistence, _ = _inference_materialization_for_fleet(memory_backend, load_turn)
    turn_112 = load_turn(112)
    assert turn_112 is not None
    players = list(iter_turn_players(turn_112))
    player_p = players[0].id
    player_q = players[1].id
    _seed_scores_rows_for_all_players(inference_persistence, turn_112)

    rescheduled_players: list[int] = []
    all_rescheduled: list[None] = []

    def spy_reschedule_row(_scope, player_id, **_kwargs):
        rescheduled_players.append(player_id)

    def spy_reschedule_all(_scope, **_kwargs):
        all_rescheduled.append(None)

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_inference_row",
        spy_reschedule_row,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_all_inference_rows",
        spy_reschedule_all,
    )

    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=persistence,
    )
    invalidation.wire_scores_invalidation_to_fleet_persistence()

    invalidation.on_fleet_ledger_persisted(628580, 1, 111, player_p)

    assert inference_persistence.get_row(628580, 1, 112, player_p) is None
    assert inference_persistence.get_row(628580, 1, 112, player_q) is not None
    assert rescheduled_players == [player_p]
    assert all_rescheduled == []
