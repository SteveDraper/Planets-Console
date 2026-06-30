"""Tests for per-player fleet ledger persistence (F7.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api.analytics.fleet.constants import FLEET_LEDGERS_KEY, FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import (
    fleet_turn_snapshot_to_json,
    persisted_fleet_ledger_to_json,
    upgrade_legacy_fleet_turn_document,
)
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
    PersistedFleetLedger,
)
from api.serialization.turn import turn_info_from_json
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    return backend


@pytest.fixture
def persistence(memory_backend):
    return FleetSnapshotPersistenceService(memory_backend)


@pytest.fixture
def sample_ledger():
    return FleetAcquisitionLedger(
        player_id=8,
        player_name="koshling",
        records=[
            FleetShipRecord(
                record_id="rec-1",
                fields=FleetShipRecordFields(ship_id=FleetFieldKnown(value=301)),
            ),
        ],
    )


def test_put_ledger_does_not_mutate_caller_persisted_ledger(persistence, sample_ledger):
    persisted = PersistedFleetLedger(
        ledger=sample_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=False,
        ),
        materialization_version=0,
    )
    persistence.put_ledger(628580, 1, 111, 8, persisted)

    assert persisted.materialization_version == 0
    loaded = persistence.get_ledger(628580, 1, 111, 8)
    assert loaded is not None
    assert loaded.materialization_version == FLEET_MATERIALIZATION_VERSION


def test_put_ledger_round_trip(persistence, sample_ledger):
    persisted = PersistedFleetLedger(
        ledger=sample_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=False,
        ),
    )
    persistence.put_ledger(628580, 1, 111, 8, persisted)
    loaded = persistence.get_ledger(628580, 1, 111, 8)
    assert loaded is not None
    assert loaded.ledger == sample_ledger
    assert loaded.provenance.turn_evidence_at_n is True
    assert loaded.provenance.prior_ledger_at_n_minus_1 is False
    assert loaded.materialization_version == FLEET_MATERIALIZATION_VERSION


def test_has_final_ledger_requires_both_provenance_flags(persistence, sample_ledger):
    partial = PersistedFleetLedger(
        ledger=sample_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=False,
        ),
    )
    final = PersistedFleetLedger(
        ledger=sample_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    persistence.put_ledger(628580, 1, 111, 8, partial)
    assert persistence.has_ledger(628580, 1, 111, 8) is True
    assert persistence.has_final_ledger(628580, 1, 111, 8) is False

    persistence.put_ledger(628580, 1, 111, 8, final)
    assert persistence.has_final_ledger(628580, 1, 111, 8) is True


def test_legacy_monolithic_document_migrates_on_has_snapshot(
    persistence,
    memory_backend,
    sample_ledger,
):
    legacy_document = {
        "analyticId": "fleet",
        "gameId": 628580,
        "perspective": 1,
        "turn": 111,
        "materializationVersion": FLEET_MATERIALIZATION_VERSION,
        "players": [persisted_fleet_ledger_to_json(PersistedFleetLedger(ledger=sample_ledger))["ledger"]],
    }
    memory_backend.put(
        persistence.document_key(628580, 1, 111),
        legacy_document,
    )

    assert persistence.has_snapshot(628580, 1, 111) is True

    stored = memory_backend.get(persistence.document_key(628580, 1, 111))
    assert isinstance(stored, dict)
    assert "players" not in stored
    assert FLEET_LEDGERS_KEY in stored
    assert "8" in stored[FLEET_LEDGERS_KEY]


def test_legacy_monolithic_document_migrates_on_read(persistence, memory_backend, sample_ledger):
    legacy_document = {
        "analyticId": "fleet",
        "gameId": 628580,
        "perspective": 1,
        "turn": 111,
        "materializationVersion": FLEET_MATERIALIZATION_VERSION,
        "players": [persisted_fleet_ledger_to_json(PersistedFleetLedger(ledger=sample_ledger))["ledger"]],
    }
    memory_backend.put(
        persistence.document_key(628580, 1, 111),
        legacy_document,
    )

    loaded = persistence.get_ledger(628580, 1, 111, 8)
    assert loaded is not None
    assert loaded.ledger == sample_ledger
    assert loaded.provenance.is_final is False

    stored = memory_backend.get(persistence.document_key(628580, 1, 111))
    assert isinstance(stored, dict)
    assert "players" not in stored
    assert FLEET_LEDGERS_KEY in stored
    assert "8" in stored[FLEET_LEDGERS_KEY]


def test_upgrade_legacy_fleet_turn_document_maps_players_to_ledgers(sample_ledger):
    legacy_document = {
        "analyticId": "fleet",
        "gameId": 628580,
        "perspective": 1,
        "turn": 111,
        "materializationVersion": FLEET_MATERIALIZATION_VERSION,
        "players": [persisted_fleet_ledger_to_json(PersistedFleetLedger(ledger=sample_ledger))["ledger"]],
    }
    upgraded = upgrade_legacy_fleet_turn_document(legacy_document)
    assert "players" not in upgraded
    assert upgraded[FLEET_LEDGERS_KEY]["8"]["provenance"] == {
        "turnEvidenceAtN": False,
        "priorLedgerAtNMinus1": False,
    }


def test_stale_per_ledger_materialization_version_is_deleted_on_read(
    persistence,
    memory_backend,
    sample_ledger,
):
    document = fleet_turn_snapshot_to_json(
        FleetTurnSnapshot(
            analytic_id="fleet",
            game_id=628580,
            perspective=1,
            turn=111,
            materialization_version=FLEET_MATERIALIZATION_VERSION,
            players=[sample_ledger],
        ),
    )
    ledger_wire = document[FLEET_LEDGERS_KEY]["8"]
    assert isinstance(ledger_wire, dict)
    ledger_wire["materializationVersion"] = FLEET_MATERIALIZATION_VERSION - 1
    memory_backend.put(persistence.document_key(628580, 1, 111), document)
    generation_before = persistence.invalidation_generation(628580, 1)

    assert persistence.get_ledger(628580, 1, 111, 8) is None
    assert persistence.has_ledger(628580, 1, 111, 8) is False
    assert persistence.invalidation_generation(628580, 1) == generation_before + 1


def test_list_ledger_player_ids_returns_sorted_ids(persistence, sample_ledger):
    other_ledger = FleetAcquisitionLedger(player_id=3, player_name="other")
    persistence.put_ledger(
        628580,
        1,
        111,
        8,
        PersistedFleetLedger(ledger=sample_ledger),
    )
    persistence.put_ledger(
        628580,
        1,
        111,
        3,
        PersistedFleetLedger(ledger=other_ledger),
    )
    assert persistence.list_ledger_player_ids(628580, 1, 111) == [3, 8]


def test_delete_ledger_removes_one_player_entry(persistence, sample_ledger):
    other_ledger = FleetAcquisitionLedger(player_id=3, player_name="other")
    persistence.put_ledger(628580, 1, 111, 8, PersistedFleetLedger(ledger=sample_ledger))
    persistence.put_ledger(628580, 1, 111, 3, PersistedFleetLedger(ledger=other_ledger))

    persistence.delete_ledger(628580, 1, 111, 8)

    assert persistence.get_ledger(628580, 1, 111, 8) is None
    assert persistence.get_ledger(628580, 1, 111, 3) is not None
