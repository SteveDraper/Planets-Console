"""Tests for fleet turn snapshot persistence and chaining."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from api.analytics.fleet.chain import (
    ensure_fleet_baseline,
    get_or_materialize_fleet_snapshot,
)
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetShipRecord, FleetTurnSnapshot
from api.errors import ValidationError
from api.serialization.turn import turn_info_from_json
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        turn_rst = json.load(f)
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
def sample_turn(memory_backend):
    return turn_info_from_json(memory_backend.get("games/628580/1/turns/111"))


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


def test_fleet_snapshot_round_trip(persistence, sample_turn):
    snapshot = ensure_fleet_baseline(628580, 1, sample_turn)
    persistence.put_snapshot(628580, 1, 111, snapshot)
    loaded = persistence.get_snapshot(628580, 1, 111)
    assert loaded == snapshot


@pytest.mark.parametrize(
    ("game_id", "perspective", "turn_number", "snapshot"),
    [
        (
            999,
            1,
            111,
            FleetTurnSnapshot(
                analytic_id="fleet",
                game_id=628580,
                perspective=1,
                turn=111,
                players=[],
            ),
        ),
        (
            628580,
            2,
            111,
            FleetTurnSnapshot(
                analytic_id="fleet",
                game_id=628580,
                perspective=1,
                turn=111,
                players=[],
            ),
        ),
        (
            628580,
            1,
            110,
            FleetTurnSnapshot(
                analytic_id="fleet",
                game_id=628580,
                perspective=1,
                turn=111,
                players=[],
            ),
        ),
    ],
)
def test_put_snapshot_rejects_metadata_mismatch(
    persistence,
    game_id,
    perspective,
    turn_number,
    snapshot,
):
    with pytest.raises(ValidationError):
        persistence.put_snapshot(game_id, perspective, turn_number, snapshot)


def test_turn_one_baseline_is_empty_per_player(persistence, load_turn, memory_backend):
    turn_one_data = copy.deepcopy(memory_backend.get("games/628580/1/turns/110"))
    assert isinstance(turn_one_data, dict)
    turn_one_data["settings"]["turn"] = 1
    turn_one_data["game"]["turn"] = 1
    memory_backend.put("games/628580/1/turns/1", turn_one_data)
    turn_one = turn_info_from_json(memory_backend.get("games/628580/1/turns/1"))

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_one,
        load_turn=load_turn,
    )
    assert snapshot.turn == 1
    assert len(snapshot.players) == 4
    assert all(player.records == [] for player in snapshot.players)
    assert persistence.get_snapshot(628580, 1, 1) == snapshot


def test_chain_materializes_turn_from_prior_snapshot(persistence, load_turn, sample_turn):
    prior = ensure_fleet_baseline(628580, 1, load_turn(110))
    prior.players[0].records.append(
        FleetShipRecord(record_id="rec-1", disposition="active"),
    )
    persistence.put_snapshot(628580, 1, 110, prior)

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        sample_turn,
        load_turn=load_turn,
    )
    assert snapshot.turn == 111
    assert len(snapshot.players[0].records) == 1
    assert snapshot.players[0].records[0].record_id == "rec-1"
    assert persistence.get_snapshot(628580, 1, 111) == snapshot


def test_invalidate_for_turn_write_drops_snapshots_at_and_after_turn(persistence):
    for turn_number in (110, 111, 112):
        persistence.put_snapshot(
            628580,
            1,
            turn_number,
            FleetTurnSnapshot(
                analytic_id="fleet",
                game_id=628580,
                perspective=1,
                turn=turn_number,
                players=[FleetAcquisitionLedger(player_id=8)],
            ),
        )
    cleared = persistence.invalidate_for_turn_write(628580, 1, 111)
    assert cleared == {111, 112}
    assert persistence.get_snapshot(628580, 1, 110) is not None
    assert persistence.get_snapshot(628580, 1, 111) is None
    assert persistence.get_snapshot(628580, 1, 112) is None


def test_turn_store_invalidates_fleet_snapshots(memory_backend):
    _, turns, _, _, _ = build_service_stack(memory_backend)
    persistence = FleetSnapshotPersistenceService(memory_backend)
    persistence.put_snapshot(
        628580,
        1,
        111,
        FleetTurnSnapshot(
            analytic_id="fleet",
            game_id=628580,
            perspective=1,
            turn=111,
            players=[FleetAcquisitionLedger(player_id=8)],
        ),
    )
    persistence.put_snapshot(
        628580,
        1,
        112,
        FleetTurnSnapshot(
            analytic_id="fleet",
            game_id=628580,
            perspective=1,
            turn=112,
            players=[FleetAcquisitionLedger(player_id=8)],
        ),
    )
    with open(ASSETS_DIR / "turn_sample.json") as f:
        turns._store_turn_rst(628580, 1, 111, json.load(f))
    assert persistence.get_snapshot(628580, 1, 111) is None
    assert persistence.get_snapshot(628580, 1, 112) is None

def test_turn_analytic_service_materializes_persisted_fleet(memory_backend, load_turn):
    persistence = FleetSnapshotPersistenceService(memory_backend)
    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(
        628580,
        1,
        110,
        ensure_fleet_baseline(628580, 1, turn_110),
    )
    _, _, _, _, analytics = build_service_stack(memory_backend)
    data = analytics.get_turn_analytics(628580, 1, 111, "fleet")
    assert data["analyticId"] == "fleet"
    assert len(data["players"]) == 4
    assert all(player["records"] == [] for player in data["players"])
    assert persistence.get_snapshot(628580, 1, 111) is not None
