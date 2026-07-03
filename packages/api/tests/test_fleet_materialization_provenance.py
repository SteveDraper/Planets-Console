"""Integration tests for per-player fleet materialization provenance (F7.2)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics.fleet.chain import (
    ensure_fleet_baseline,
    get_or_materialize_fleet_ledger_for_player,
    get_or_materialize_fleet_snapshot,
)
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization, FleetInferenceSupport
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.turn_roster import iter_turn_players
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.serialization.turn import turn_info_from_json
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
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


def test_partial_scores_closure_persists_non_final_provenance(persistence, load_turn):
    """Incomplete scores@N leaves turnEvidenceAtN false; ledger is not ensure-final."""
    turn = load_turn(111)
    assert turn is not None
    player_id = turn.scores[0].ownerid
    inference_persistence = InferenceRowPersistenceService(persistence._storage)
    scores_services = ScoresExportContext(persistence=inference_persistence)
    inference_materialization = FleetInferenceMaterialization(
        inference=FleetInferenceSupport(scores_services=scores_services),
        load_turn=load_turn,
    )

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_id,
        turn,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )

    loaded = persistence.get_ledger(628580, 1, 111, player_id)
    assert loaded is not None
    assert loaded.provenance.turn_evidence_at_n is False
    assert loaded.provenance.prior_ledger_at_n_minus_1 is False
    assert loaded.provenance.is_final is False
    assert persistence.has_ledger(628580, 1, 111, player_id) is True
    assert persistence.has_final_ledger(628580, 1, 111, player_id) is False


def test_complete_scores_closure_persists_final_provenance_when_prior_final(
    persistence,
    load_turn,
    memory_backend,
):
    """When scores@N and fleet@(N-1) legs are closed, provenance is final."""
    from dataclasses import replace

    turn_one_data = copy.deepcopy(memory_backend.get("games/628580/1/turns/110"))
    assert isinstance(turn_one_data, dict)
    turn_one_data["settings"]["turn"] = 1
    turn_one_data["game"]["turn"] = 1
    memory_backend.put("games/628580/1/turns/1", turn_one_data)
    turn_one = turn_info_from_json(memory_backend.get("games/628580/1/turns/1"))

    turn_two_data = copy.deepcopy(turn_one_data)
    turn_two_data["settings"]["turn"] = 2
    turn_two_data["game"]["turn"] = 2
    memory_backend.put("games/628580/1/turns/2", turn_two_data)
    turn_two = turn_info_from_json(memory_backend.get("games/628580/1/turns/2"))

    player_id = turn_one.scores[0].ownerid
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    scores_services = ScoresExportContext(persistence=inference_persistence)
    inference_materialization = FleetInferenceMaterialization(
        inference=FleetInferenceSupport(scores_services=scores_services),
        load_turn=load_turn,
    )

    def load_turn_one_two(turn_number: int):
        if turn_number in (1, 2):
            return turn_info_from_json(memory_backend.get(f"games/628580/1/turns/{turn_number}"))
        return load_turn(turn_number)

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_id,
        turn_one,
        load_turn=load_turn_one_two,
        inference_materialization=FleetInferenceMaterialization(
            inference=inference_materialization.inference,
            load_turn=load_turn_one_two,
        ),
    )
    prior = persistence.get_ledger(628580, 1, 1, player_id)
    assert prior is not None
    assert prior.provenance.is_final is True

    turn_two = replace(
        turn_two,
        scores=[
            replace(
                score,
                turn=2,
                ownerid=player_id,
                shipchange=1,
                freighterchange=0,
            )
            for score in turn_two.scores
            if score.ownerid == player_id
        ],
    )
    inference_persistence.put_row(
        628580,
        1,
        2,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="done",
            solution_count=1,
            is_complete=True,
            solutions=[],
        ),
    )

    get_or_materialize_fleet_ledger_for_player(
        persistence,
        628580,
        1,
        player_id,
        turn_two,
        load_turn=load_turn_one_two,
        inference_materialization=FleetInferenceMaterialization(
            inference=inference_materialization.inference,
            load_turn=load_turn_one_two,
        ),
    )
    loaded = persistence.get_ledger(628580, 1, 2, player_id)
    assert loaded is not None
    assert loaded.provenance.turn_evidence_at_n is True
    assert loaded.provenance.prior_ledger_at_n_minus_1 is True
    assert loaded.provenance.is_final is True
    assert persistence.has_final_ledger(628580, 1, 2, player_id) is True


def test_turn_context_includes_max_ship_id_bound(load_turn):
    turn = load_turn(111)
    assert turn is not None
    context = FleetTurnContext.from_turn(turn)
    assert context.max_ship_id_bound is not None


def test_snapshot_gap_fill_reuses_turn_context_across_players(persistence, load_turn):
    turn = load_turn(111)
    assert turn is not None
    player_count = len(list(iter_turn_players(turn)))
    assert player_count > 1

    with patch(
        "api.analytics.fleet.chain.FleetTurnContext.from_turn",
        wraps=FleetTurnContext.from_turn,
    ) as from_turn_mock:
        get_or_materialize_fleet_snapshot(
            persistence,
            628580,
            1,
            turn,
            load_turn=load_turn,
        )

    # Each player gap-fills with its own chain; turn context is built per turn per chain.
    assert from_turn_mock.call_count == 2 * player_count


def test_gap_fill_persists_per_player_ledgers_with_provenance(persistence, load_turn):
    turn = load_turn(111)
    assert turn is not None

    get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn,
        load_turn=load_turn,
    )

    player_ids = persistence.list_ledger_player_ids(628580, 1, 111)
    assert len(player_ids) == len(list(iter_turn_players(turn)))
    for player_id in player_ids:
        loaded = persistence.get_ledger(628580, 1, 111, player_id)
        assert loaded is not None
        assert loaded.provenance is not None


def test_gap_fill_persists_intermediate_turn_per_player(persistence, load_turn):
    turn_110 = load_turn(110)
    assert turn_110 is not None
    turn = load_turn(111)
    assert turn is not None
    player_id = turn.scores[0].ownerid

    persistence.put_snapshot(
        628580,
        1,
        110,
        ensure_fleet_baseline(628580, 1, turn_110),
    )

    get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn,
        load_turn=load_turn,
    )

    intermediate = persistence.get_ledger(628580, 1, 111, player_id)
    assert intermediate is not None
    assert persistence.get_ledger(628580, 1, 110, player_id) is not None
