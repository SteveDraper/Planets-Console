"""Tests for :mod:`clear_analytic_persistence`."""

from __future__ import annotations

import pytest
from api.analytics.fleet.constants import FLEET_LEDGERS_KEY, FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)
from api.errors import NotFoundError
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend
from clear_analytic_persistence import (
    clear_analytic_persistence,
    parse_selector,
)


def _put_fleet_ledger(
    storage: MemoryAssetBackend,
    *,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
) -> None:
    fleet = FleetSnapshotPersistenceService(storage)
    ledger = FleetAcquisitionLedger(
        player_id=player_id,
        player_name=f"player-{player_id}",
        records=[
            FleetShipRecord(
                record_id=f"rec-{player_id}",
                fields=FleetShipRecordFields(ship_id=FleetFieldKnown(value=player_id)),
            ),
        ],
    )
    fleet.put_ledger(
        game_id,
        perspective,
        turn,
        player_id,
        PersistedFleetLedger(
            ledger=ledger,
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=False,
            ),
            materialization_version=FLEET_MATERIALIZATION_VERSION,
        ),
    )


def _put_scores_row(
    storage: MemoryAssetBackend,
    *,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
) -> None:
    key = InferenceRowPersistenceService.row_store_key(game_id, perspective, turn, player_id)
    storage.put(
        key,
        {
            "playerId": player_id,
            "status": "exact",
            "summary": {},
            "solutions": [],
        },
    )


def _put_hull_mask(storage: MemoryAssetBackend, *, game_id: int, player_id: int) -> None:
    storage.put(
        f"games/{game_id}/analytics/scores/inference_hull_catalog_masks/{player_id}",
        {"enabledHullIds": [1, 2]},
    )


@pytest.fixture
def storage() -> MemoryAssetBackend:
    backend = MemoryAssetBackend(initial={})
    backend.put("games/628580/info", {"name": "test"})
    return backend


def test_parse_selector_wildcard_and_int() -> None:
    assert parse_selector("*", label="perspective") is None
    assert parse_selector("11", label="perspective") == 11
    with pytest.raises(ValueError, match="perspective"):
        parse_selector("x", label="perspective")


def test_clear_perspective_all_players_removes_turn_docs(storage: MemoryAssetBackend) -> None:
    _put_fleet_ledger(storage, game_id=628580, perspective=11, turn=3, player_id=8)
    _put_fleet_ledger(storage, game_id=628580, perspective=11, turn=3, player_id=9)
    _put_scores_row(storage, game_id=628580, perspective=11, turn=3, player_id=8)
    _put_fleet_ledger(storage, game_id=628580, perspective=1, turn=3, player_id=8)

    result = clear_analytic_persistence(
        storage,
        game_id=628580,
        perspective=11,
        player_id=None,
    )

    assert "games/628580/11/turns/3/analytics/fleet" in result.deleted_documents
    assert "games/628580/11/turns/3/analytics/scores" in result.deleted_documents
    with pytest.raises(NotFoundError):
        storage.get("games/628580/11/turns/3/analytics/fleet")
    # Other perspective untouched.
    assert storage.get("games/628580/1/turns/3/analytics/fleet")[FLEET_LEDGERS_KEY]


def test_clear_one_player_keeps_other_player_entries(storage: MemoryAssetBackend) -> None:
    _put_fleet_ledger(storage, game_id=628580, perspective=11, turn=4, player_id=8)
    _put_fleet_ledger(storage, game_id=628580, perspective=11, turn=4, player_id=9)
    _put_scores_row(storage, game_id=628580, perspective=11, turn=4, player_id=8)
    _put_scores_row(storage, game_id=628580, perspective=11, turn=4, player_id=9)
    _put_hull_mask(storage, game_id=628580, player_id=8)
    _put_hull_mask(storage, game_id=628580, player_id=9)

    result = clear_analytic_persistence(
        storage,
        game_id=628580,
        perspective=11,
        player_id=8,
    )

    assert any(key.endswith("/ledgers/8") for key in result.deleted_player_entries)
    assert any(key.endswith("/inference_rows/8") for key in result.deleted_player_entries)
    fleet = FleetSnapshotPersistenceService(storage)
    assert fleet.get_ledger(628580, 11, 4, 8) is None
    assert fleet.get_ledger(628580, 11, 4, 9) is not None
    scores = InferenceRowPersistenceService(storage)
    assert scores.get_row(628580, 11, 4, 8) is None
    # Raw get still works for remaining row even if schema is minimal.
    assert storage.get(scores.row_store_key(628580, 11, 4, 9))["playerId"] == 9
    with pytest.raises(NotFoundError):
        storage.get("games/628580/analytics/scores/inference_hull_catalog_masks/8")
    assert storage.get("games/628580/analytics/scores/inference_hull_catalog_masks/9")


def test_clear_all_perspectives_one_player(storage: MemoryAssetBackend) -> None:
    _put_fleet_ledger(storage, game_id=628580, perspective=1, turn=2, player_id=7)
    _put_fleet_ledger(storage, game_id=628580, perspective=11, turn=2, player_id=7)
    _put_fleet_ledger(storage, game_id=628580, perspective=11, turn=2, player_id=8)

    clear_analytic_persistence(
        storage,
        game_id=628580,
        perspective=None,
        player_id=7,
    )

    fleet = FleetSnapshotPersistenceService(storage)
    assert fleet.get_ledger(628580, 1, 2, 7) is None
    assert fleet.get_ledger(628580, 11, 2, 7) is None
    assert fleet.get_ledger(628580, 11, 2, 8) is not None


def test_full_wildcard_clears_game_global_non_player(storage: MemoryAssetBackend) -> None:
    storage.put("games/628580/analytics/homeworld-locator", {"candidates": []})
    storage.put("games/628580/11/analytics/homeworld-locator", {"evidence": {}})
    _put_fleet_ledger(storage, game_id=628580, perspective=11, turn=1, player_id=8)

    result = clear_analytic_persistence(
        storage,
        game_id=628580,
        perspective=None,
        player_id=None,
    )

    assert "games/628580/analytics/homeworld-locator" in result.deleted_documents
    assert "games/628580/11/analytics/homeworld-locator" in result.deleted_documents
    with pytest.raises(NotFoundError):
        storage.get("games/628580/11/turns/1/analytics/fleet")


def test_dry_run_does_not_mutate(storage: MemoryAssetBackend) -> None:
    _put_fleet_ledger(storage, game_id=628580, perspective=11, turn=5, player_id=8)
    result = clear_analytic_persistence(
        storage,
        game_id=628580,
        perspective=11,
        player_id=None,
        dry_run=True,
    )
    assert result.deleted_documents
    assert storage.get("games/628580/11/turns/5/analytics/fleet")[FLEET_LEDGERS_KEY]
