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
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _legacy_player_wire(ledger: FleetAcquisitionLedger) -> dict:
    return persisted_fleet_ledger_to_json(PersistedFleetLedger(ledger=ledger))["ledger"]


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


def test_put_snapshot_stamps_non_final_provenance_per_ledger(persistence, sample_ledger):
    snapshot = FleetTurnSnapshot(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=111,
        materialization_version=FLEET_MATERIALIZATION_VERSION,
        players=[sample_ledger],
    )
    persistence.put_snapshot(628580, 1, 111, snapshot)

    loaded = persistence.get_ledger(628580, 1, 111, 8)
    assert loaded is not None
    assert loaded.ledger == sample_ledger
    assert loaded.provenance.is_final is False
    assert persistence.has_final_ledger(628580, 1, 111, 8) is False


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
        "players": [_legacy_player_wire(sample_ledger)],
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
        "players": [_legacy_player_wire(sample_ledger)],
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
        "players": [_legacy_player_wire(sample_ledger)],
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
    generation_before = persistence.player_invalidation_generation(628580, 1, 8)

    assert persistence.get_ledger(628580, 1, 111, 8) is None
    assert persistence.has_ledger(628580, 1, 111, 8) is False
    assert persistence.player_invalidation_generation(628580, 1, 8) == generation_before + 1
    assert persistence.turn_invalidation_generation(628580, 1, 8, 111) == 1
    assert persistence.player_invalidation_generation(628580, 1, 3) == 0


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


def test_put_ledger_does_not_invoke_on_snapshot_persisted(persistence, sample_ledger):
    callback_turns: list[int] = []

    def on_snapshot_persisted(_game_id: int, _perspective: int, turn_number: int) -> None:
        callback_turns.append(turn_number)

    persistence.on_snapshot_persisted = on_snapshot_persisted
    final = PersistedFleetLedger(
        ledger=sample_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    persistence.put_ledger(628580, 1, 111, 8, final)
    assert callback_turns == []


def test_put_snapshot_still_supports_legacy_snapshot_callback(persistence, sample_ledger):
    callback_turns: list[int] = []

    def on_snapshot_persisted(_game_id: int, _perspective: int, turn_number: int) -> None:
        callback_turns.append(turn_number)

    persistence.on_snapshot_persisted = on_snapshot_persisted
    snapshot = FleetTurnSnapshot(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=111,
        materialization_version=FLEET_MATERIALIZATION_VERSION,
        players=[sample_ledger],
    )
    persistence.put_snapshot(628580, 1, 111, snapshot)
    assert callback_turns == [111]


def _final_provenance() -> FleetMaterializationProvenance:
    return FleetMaterializationProvenance(
        turn_evidence_at_n=True,
        prior_ledger_at_n_minus_1=True,
    )


def test_put_ledger_notifies_on_ensure_final_transition(persistence, sample_ledger):
    callbacks: list[tuple[int, int]] = []
    persistence.on_ledger_persisted = lambda event: callbacks.append(
        (event.fleet_turn, event.player_id)
    )

    partial = PersistedFleetLedger(
        ledger=sample_ledger,
        provenance=FleetMaterializationProvenance(turn_evidence_at_n=True),
    )
    persistence.put_ledger(628580, 1, 111, 8, partial)
    assert callbacks == []

    persistence.put_ledger(
        628580,
        1,
        111,
        8,
        PersistedFleetLedger(ledger=sample_ledger, provenance=_final_provenance()),
    )
    assert callbacks == [(111, 8)]


def test_put_ledger_can_defer_final_transition_notification(persistence, sample_ledger):
    callbacks: list[tuple[int, int]] = []
    persistence.on_ledger_persisted = lambda event: callbacks.append(
        (event.fleet_turn, event.player_id)
    )

    notification = persistence.put_ledger(
        628580,
        1,
        111,
        8,
        PersistedFleetLedger(ledger=sample_ledger, provenance=_final_provenance()),
        defer_ledger_persisted_notification=True,
    )

    assert callbacks == []
    assert notification is not None
    notification()
    assert callbacks == [(111, 8)]


def test_put_ledger_notifies_on_final_ledger_version_bump(
    persistence,
    memory_backend,
    sample_ledger,
):
    callbacks: list[tuple[int, int]] = []
    persistence.on_ledger_persisted = lambda event: callbacks.append(
        (event.fleet_turn, event.player_id)
    )
    final = PersistedFleetLedger(ledger=sample_ledger, provenance=_final_provenance())

    persistence.put_ledger(628580, 1, 111, 8, final)
    assert callbacks == [(111, 8)]

    persistence.put_ledger(628580, 1, 111, 8, final)
    assert callbacks == [(111, 8)]

    document = memory_backend.get(persistence.document_key(628580, 1, 111))
    assert isinstance(document, dict)
    ledger_wire = document[FLEET_LEDGERS_KEY]["8"]
    assert isinstance(ledger_wire, dict)
    ledger_wire["materializationVersion"] = FLEET_MATERIALIZATION_VERSION - 1
    memory_backend.put(persistence.document_key(628580, 1, 111), document)

    persistence.put_ledger(628580, 1, 111, 8, final)
    assert callbacks == [(111, 8), (111, 8)]
