"""Tests for fleet turn snapshot persistence and chaining."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics.fleet.chain import (
    ensure_fleet_baseline,
    get_or_materialize_fleet_snapshot,
)
from api.analytics.fleet.constants import FLEET_LEDGERS_KEY, FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.gap_fill_coordinator import reset_coordinators
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import fleet_turn_snapshot_to_json
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetTurnSnapshot,
    PersistedFleetLedger,
)
from api.errors import NotFoundError, ValidationError
from api.serialization.turn import turn_info_from_json
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


# Coordinator registry reset is called in coordinator-focused tests.


@pytest.fixture(autouse=True)
def _reset_fleet_gap_fill_coordinators():
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


def test_turn_one_baseline_seeds_from_turn_one_sightings(persistence, load_turn, memory_backend):
    turn_one_data = copy.deepcopy(memory_backend.get("games/628580/1/turns/110"))
    assert isinstance(turn_one_data, dict)
    turn_one_data["settings"]["turn"] = 1
    turn_one_data["game"]["turn"] = 1
    turn_one_data["ships"] = [turn_one_data["ships"][0]]
    turn_one_data["ships"][0]["id"] = 99
    turn_one_data["ships"][0]["ownerid"] = 8
    turn_one_data["ships"][0]["turnkilled"] = 0
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
    assert len(snapshot.players[0].records) == 1
    assert snapshot.players[0].records[0].fields.ship_id == FleetFieldKnown(value=99)
    assert persistence.get_snapshot(628580, 1, 1) == snapshot


def _put_turn_rst(memory_backend, turn_number: int, template_turn_number: int = 111) -> None:
    template = memory_backend.get(f"games/628580/1/turns/{template_turn_number}")
    assert isinstance(template, dict)
    turn_rst = copy.deepcopy(template)
    turn_rst["settings"]["turn"] = turn_number
    turn_rst["game"]["turn"] = turn_number
    memory_backend.put(f"games/628580/1/turns/{turn_number}", turn_rst)


def test_chain_gap_fill_persists_intermediate_turn(persistence, load_turn, memory_backend):
    turn_110 = load_turn(110)
    assert turn_110 is not None
    prior = ensure_fleet_baseline(628580, 1, turn_110)
    prior.players[0].records.append(
        FleetShipRecord(record_id="gap-rec", disposition="active"),
    )
    persistence.put_snapshot(628580, 1, 110, prior)

    turn_112 = load_turn(112)
    assert turn_112 is not None
    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_112,
        load_turn=load_turn,
    )

    assert snapshot.turn == 112
    assert len(snapshot.players[0].records) == 6
    assert snapshot.players[0].records[0].record_id == "gap-rec"
    intermediate = persistence.get_snapshot(628580, 1, 111)
    assert intermediate is not None
    assert intermediate.turn == 111
    assert len(intermediate.players[0].records) == 6
    assert persistence.get_snapshot(628580, 1, 112) == snapshot


def test_chain_raises_when_intermediate_rst_missing(persistence, load_turn, memory_backend):
    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(
        628580,
        1,
        110,
        ensure_fleet_baseline(628580, 1, turn_110),
    )
    memory_backend.delete("games/628580/1/turns/111")

    turn_112 = load_turn(112)
    assert turn_112 is not None
    with pytest.raises(NotFoundError, match="requires stored turn 111"):
        get_or_materialize_fleet_snapshot(
            persistence,
            628580,
            1,
            turn_112,
            load_turn=load_turn,
        )
    assert persistence.get_snapshot(628580, 1, 112) is None


def test_implicit_turn_one_baseline_without_persisting_turn_one(
    persistence,
    load_turn,
    memory_backend,
    sample_turn,
):
    for turn_number in range(2, 110):
        _put_turn_rst(memory_backend, turn_number)

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        sample_turn,
        load_turn=load_turn,
    )

    assert snapshot.turn == 111
    assert len(snapshot.players) == 4
    assert len(snapshot.players[0].records) == 5
    assert persistence.get_snapshot(628580, 1, 1) is None
    assert persistence.get_snapshot(628580, 1, 111) == snapshot


def test_implicit_baseline_when_only_later_turn_rst_stored(
    persistence,
    load_turn,
    memory_backend,
):
    _put_turn_rst(memory_backend, 3)
    turn_three = load_turn(3)
    assert turn_three is not None

    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_three,
        load_turn=load_turn,
    )

    assert snapshot.turn == 3
    assert len(snapshot.players) == 4
    assert persistence.get_snapshot(628580, 1, 1) is None
    assert persistence.get_snapshot(628580, 1, 2) is None
    assert persistence.get_snapshot(628580, 1, 3) == snapshot


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
    assert len(snapshot.players[0].records) == 6
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
    assert persistence.invalidation_generation(628580, 1, 8) == 0
    cleared = persistence.invalidate_for_turn_write(628580, 1, 111)
    assert cleared == {111, 112}
    assert persistence.invalidation_generation(628580, 1, 8) == 1
    assert persistence.get_snapshot(628580, 1, 110) is not None
    assert persistence.get_snapshot(628580, 1, 111) is None
    assert persistence.get_snapshot(628580, 1, 112) is None


def test_invalidate_player_ledgers_from_turn_drops_only_target_player(persistence):
    player_8 = FleetAcquisitionLedger(player_id=8)
    player_3 = FleetAcquisitionLedger(player_id=3)
    for turn_number in (110, 111, 112):
        persistence.put_ledger(
            628580,
            1,
            turn_number,
            8,
            PersistedFleetLedger(ledger=player_8),
        )
        persistence.put_ledger(
            628580,
            1,
            turn_number,
            3,
            PersistedFleetLedger(ledger=player_3),
        )
    assert persistence.invalidation_generation(628580, 1, 8) == 0
    assert persistence.invalidation_generation(628580, 1, 3) == 0
    cleared = persistence.invalidate_player_ledgers_from_turn(628580, 1, 111, 8)
    assert cleared == {111, 112}
    assert persistence.invalidation_generation(628580, 1, 8) == 1
    assert persistence.invalidation_generation(628580, 1, 3) == 0
    assert persistence.get_ledger(628580, 1, 110, 8) is not None
    assert persistence.get_ledger(628580, 1, 110, 3) is not None
    assert persistence.get_ledger(628580, 1, 111, 8) is None
    assert persistence.get_ledger(628580, 1, 112, 8) is None
    assert persistence.get_ledger(628580, 1, 111, 3) is not None
    assert persistence.get_ledger(628580, 1, 112, 3) is not None


def test_invalidation_bumps_epoch_for_target_player_only(persistence):
    """invalidate_player_ledgers_from_turn bumps only the target player's generation."""
    player_8 = FleetAcquisitionLedger(player_id=8)
    player_3 = FleetAcquisitionLedger(player_id=3)
    for turn_number in (111, 112):
        persistence.put_ledger(
            628580,
            1,
            turn_number,
            8,
            PersistedFleetLedger(ledger=player_8),
        )
        persistence.put_ledger(
            628580,
            1,
            turn_number,
            3,
            PersistedFleetLedger(ledger=player_3),
        )

    assert persistence.invalidation_generation(628580, 1, 8) == 0
    assert persistence.invalidation_generation(628580, 1, 3) == 0
    persistence.invalidate_player_ledgers_from_turn(628580, 1, 111, 8)
    assert persistence.invalidation_generation(628580, 1, 8) == 1
    assert persistence.invalidation_generation(628580, 1, 3) == 0


def test_player_scoped_and_turn_scoped_invalidation_generations_are_independent(persistence):
    """Player-wide and turn-scoped fleet epochs bump separately."""
    assert persistence.invalidation_generation(628580, 1, 8) == 0
    assert persistence.invalidation_generation(628580, 1, 8, turn=4) == 0
    assert persistence.invalidation_generation(628580, 1, 8, turn=5) == 0

    persistence.bump_invalidation_generation(628580, 1, 8)
    assert persistence.invalidation_generation(628580, 1, 8) == 1
    assert persistence.invalidation_generation(628580, 1, 8, turn=4) == 0

    persistence.bump_invalidation_generation(628580, 1, 8, turn=4)
    assert persistence.invalidation_generation(628580, 1, 8) == 1
    assert persistence.invalidation_generation(628580, 1, 8, turn=4) == 1
    assert persistence.invalidation_generation(628580, 1, 8, turn=5) == 0

    persistence.put_ledger(
        628580,
        1,
        5,
        8,
        PersistedFleetLedger(ledger=FleetAcquisitionLedger(player_id=8)),
    )
    persistence.invalidate_player_ledgers_from_turn(628580, 1, 5, 8)
    assert persistence.invalidation_generation(628580, 1, 8) == 2
    assert persistence.invalidation_generation(628580, 1, 8, turn=4) == 1
    assert persistence.invalidation_generation(628580, 1, 8, turn=5) == 1


def test_turn_document_replace_bumps_all_player_epochs(persistence):
    """invalidate_for_turn_write bumps every player who had ledgers at affected turns."""
    player_8 = FleetAcquisitionLedger(player_id=8)
    player_3 = FleetAcquisitionLedger(player_id=3)
    for turn_number in (110, 111, 112):
        persistence.put_ledger(
            628580,
            1,
            turn_number,
            8,
            PersistedFleetLedger(ledger=player_8),
        )
        persistence.put_ledger(
            628580,
            1,
            turn_number,
            3,
            PersistedFleetLedger(ledger=player_3),
        )

    assert persistence.invalidation_generation(628580, 1, 8) == 0
    assert persistence.invalidation_generation(628580, 1, 3) == 0
    cleared = persistence.invalidate_for_turn_write(628580, 1, 111)
    assert cleared == {111, 112}
    assert persistence.invalidation_generation(628580, 1, 8) == 1
    assert persistence.invalidation_generation(628580, 1, 3) == 1
    assert persistence.get_ledger(628580, 1, 110, 8) is not None
    assert persistence.get_ledger(628580, 1, 110, 3) is not None


def test_inference_evidence_updated_preserves_other_players_ledgers(memory_backend):
    fleet_persistence, inference_persistence, _, _ = _wired_fleet_inference_services(memory_backend)
    player_8 = FleetAcquisitionLedger(player_id=8)
    player_3 = FleetAcquisitionLedger(player_id=3)
    for turn_number in (111, 112):
        fleet_persistence.put_ledger(
            628580,
            1,
            turn_number,
            8,
            PersistedFleetLedger(ledger=player_8),
        )
        fleet_persistence.put_ledger(
            628580,
            1,
            turn_number,
            3,
            PersistedFleetLedger(ledger=player_3),
        )
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    inference_persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status="exact",
            summary="updated",
            solution_count=1,
            is_complete=True,
            solutions=[],
        ),
    )
    assert fleet_persistence.get_ledger(628580, 1, 111, 8) is None
    assert fleet_persistence.get_ledger(628580, 1, 112, 8) is None
    assert fleet_persistence.get_ledger(628580, 1, 111, 3) is not None
    assert fleet_persistence.get_ledger(628580, 1, 112, 3) is not None


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
    koshling = next(player for player in data["players"] if player["playerId"] == 8)
    assert len(koshling["records"]) == 5
    assert persistence.get_snapshot(628580, 1, 111) is not None


def _wired_fleet_inference_services(memory_backend):
    fleet_persistence = FleetSnapshotPersistenceService(memory_backend)
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=fleet_persistence,
    )
    invalidation.wire_fleet_invalidation_to_persistence()
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
    )

    scheduler = InferenceRowScheduler(
        worker_count=0,
        on_row_complete=inference_persistence.persist_row_complete,
        on_held_solutions_updated=lambda session: invalidation.on_inference_evidence_updated(
            session.game_id,
            session.perspective,
            session.turn_number,
            session.player_id,
        ),
    )
    invalidation.bind_scheduler(scheduler)
    return fleet_persistence, inference_persistence, invalidation, scheduler


def test_inference_row_persisted_invalidates_cached_fleet_for_refinement(
    memory_backend,
    load_turn,
):
    from api.analytics.fleet.held_solutions import (
        FleetInferenceMaterialization,
        FleetInferenceSupport,
    )
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.scores.export_services import ScoresExportContext
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    from tests.scores_exports_helpers import ship_build_wire

    fleet_persistence, inference_persistence, _, scheduler = _wired_fleet_inference_services(
        memory_backend
    )
    turn = load_turn(111)
    assert turn is not None
    turn_110 = load_turn(110)
    assert turn_110 is not None

    def load_turn_fn(turn_number: int):
        return load_turn(turn_number)

    scores_services = ScoresExportContext(
        persistence=inference_persistence,
        scheduler=scheduler,
    )
    inference_materialization = FleetInferenceMaterialization(
        inference=FleetInferenceSupport(scores_services=scores_services),
        load_turn=load_turn_fn,
    )
    fleet_persistence.put_snapshot(
        628580,
        1,
        110,
        ensure_fleet_baseline(628580, 1, turn_110),
    )

    snapshot = get_or_materialize_fleet_snapshot(
        fleet_persistence,
        628580,
        1,
        turn,
        load_turn=load_turn_fn,
        inference_materialization=inference_materialization,
    )
    koshling = next(ledger for ledger in snapshot.players if ledger.player_id == 8)
    placeholder = next(
        record
        for record in koshling.records
        if any(event.kind == "scoreboard_delta" for event in record.events)
    )
    assert placeholder.build_option_sets == []
    assert fleet_persistence.get_snapshot(628580, 1, 111) is not None

    inference_persistence.put_row(
        628580,
        1,
        111,
        8,
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
    assert fleet_persistence.get_ledger(628580, 1, 111, 8) is None
    other_player_ids = [
        player_id
        for player_id in fleet_persistence.list_ledger_player_ids(628580, 1, 111)
        if player_id != 8
    ]
    assert other_player_ids

    rematerialized = get_or_materialize_fleet_snapshot(
        fleet_persistence,
        628580,
        1,
        turn,
        load_turn=load_turn_fn,
        inference_materialization=inference_materialization,
    )
    koshling_refined = next(ledger for ledger in rematerialized.players if ledger.player_id == 8)
    refined_placeholder = next(
        record
        for record in koshling_refined.records
        if any(event.kind == "scoreboard_delta" for event in record.events)
    )
    assert len(refined_placeholder.build_option_sets) == 1
    assert refined_placeholder.build_option_sets[0].hull_id == 13


def test_held_solutions_scheduler_callback_invalidates_cached_fleet_snapshot(
    sample_turn,
    memory_backend,
):
    from api.analytics.military_score_inference.inference_stream_rows import (
        schedule_inference_row,
    )

    fleet_persistence, _, _, scheduler = _wired_fleet_inference_services(memory_backend)
    player_id = 8
    turn_number = sample_turn.settings.turn
    fleet_persistence.put_snapshot(
        628580,
        1,
        turn_number,
        FleetTurnSnapshot(
            analytic_id="fleet",
            game_id=628580,
            perspective=1,
            turn=turn_number,
            players=[FleetAcquisitionLedger(player_id=player_id)],
        ),
    )

    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=1,
    )
    assert scheduled is not None
    assert scheduler._on_held_solutions_updated is not None
    scheduler._on_held_solutions_updated(scheduled.session)

    assert fleet_persistence.get_ledger(628580, 1, turn_number, player_id) is None


def test_gap_fill_aborts_on_concurrent_invalidation(persistence, load_turn, memory_backend):
    from api.errors import FleetGapFillEpochInvalidated

    turn_110 = load_turn(110)
    assert turn_110 is not None
    prior = ensure_fleet_baseline(628580, 1, turn_110)
    prior.players[0].records.append(
        FleetShipRecord(record_id="gap-rec", disposition="active"),
    )
    persistence.put_snapshot(628580, 1, 110, prior)

    turn_112 = load_turn(112)
    assert turn_112 is not None
    sync = threading.Barrier(2)
    put_records: list[tuple[int, int]] = []
    original_put_ledger = persistence.put_ledger

    def hooked_put_ledger(*args, **kwargs):
        original_put_ledger(*args, **kwargs)
        player_id = args[3]
        put_records.append(
            (player_id, persistence.invalidation_generation(628580, 1, player_id)),
        )
        if len(put_records) == 1:
            sync.wait()
            sync.wait()

    persistence.put_ledger = hooked_put_ledger  # type: ignore[method-assign]

    gap_fill_error: BaseException | None = None

    def run_gap_fill() -> None:
        nonlocal gap_fill_error
        try:
            get_or_materialize_fleet_snapshot(
                persistence,
                628580,
                1,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            gap_fill_error = exc

    gap_fill_thread = threading.Thread(target=run_gap_fill)
    gap_fill_thread.start()
    sync.wait()
    persistence.invalidate_for_turn_write(628580, 1, 111)
    sync.wait()
    gap_fill_thread.join()

    assert isinstance(gap_fill_error, FleetGapFillEpochInvalidated)
    # Torn-tail guard: abort before persisting later turns on a stale generation.
    assert persistence.get_snapshot(628580, 1, 112) is None

    persistence.put_ledger = original_put_ledger  # type: ignore[method-assign]
    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_112,
        load_turn=load_turn,
    )
    assert snapshot.turn == 112
    assert persistence.get_snapshot(628580, 1, 112) == snapshot
    assert len(snapshot.players[0].records) == 6
    assert snapshot.players[0].records[0].record_id == "gap-rec"


def test_gap_fill_does_not_persist_torn_tail_after_mid_chain_invalidation(persistence, load_turn):
    from api.errors import FleetGapFillEpochInvalidated

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_112 = load_turn(112)
    assert turn_112 is not None
    hook_at_first_barrier = threading.Event()
    main_released_first_barrier = threading.Event()
    hook_at_second_barrier = threading.Event()
    main_released_second_barrier = threading.Event()
    attempt_puts: list[list[int]] = []
    current_attempt_puts: list[int] = []
    mid_chain_intercepted = False
    original_put_ledger = persistence.put_ledger

    def hooked_put_ledger(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        persisted,
        **kwargs,
    ) -> None:
        nonlocal mid_chain_intercepted
        original_put_ledger(
            game_id,
            perspective,
            turn_number,
            player_id,
            persisted,
            **kwargs,
        )
        current_attempt_puts.append(turn_number)
        if turn_number == 111 and not mid_chain_intercepted:
            mid_chain_intercepted = True
            assert persistence.get_snapshot(628580, 1, 112) is None
            hook_at_first_barrier.set()
            assert main_released_first_barrier.wait(timeout=5)
            persistence.invalidate_for_turn_write(628580, 1, 111)
            assert persistence.get_snapshot(628580, 1, 112) is None
            attempt_puts.append(list(current_attempt_puts))
            current_attempt_puts.clear()
            hook_at_second_barrier.set()
            assert main_released_second_barrier.wait(timeout=5)

    persistence.put_ledger = hooked_put_ledger  # type: ignore[method-assign]

    gap_fill_error: BaseException | None = None

    def run_gap_fill() -> None:
        nonlocal gap_fill_error
        try:
            get_or_materialize_fleet_snapshot(
                persistence,
                628580,
                1,
                turn_112,
                load_turn=load_turn,
            )
        except BaseException as exc:
            gap_fill_error = exc

    gap_fill_thread = threading.Thread(target=run_gap_fill)
    gap_fill_thread.start()
    assert hook_at_first_barrier.wait(timeout=5)
    main_released_first_barrier.set()
    assert hook_at_second_barrier.wait(timeout=5)
    main_released_second_barrier.set()
    gap_fill_thread.join(timeout=5)

    assert not gap_fill_thread.is_alive()
    assert isinstance(gap_fill_error, FleetGapFillEpochInvalidated)
    assert attempt_puts[0] == [111]
    assert persistence.get_snapshot(628580, 1, 112) is None

    persistence.put_ledger = original_put_ledger  # type: ignore[method-assign]
    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_112,
        load_turn=load_turn,
    )
    assert snapshot.turn == 112
    assert persistence.get_snapshot(628580, 1, 112) == snapshot


def test_gap_fill_aborts_on_mid_chain_invalidation_without_spin(persistence, load_turn):
    """Single-attempt abort: continuous put-time invalidation must not spin retries."""
    from api.errors import FleetGapFillEpochInvalidated

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_111 = load_turn(111)
    assert turn_111 is not None
    original_put_ledger = persistence.put_ledger

    def put_ledger_that_invalidates(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        persisted,
        **kwargs,
    ) -> None:
        original_put_ledger(
            game_id,
            perspective,
            turn_number,
            player_id,
            persisted,
            **kwargs,
        )
        persistence.invalidate_for_turn_write(game_id, perspective, turn_number)

    persistence.put_ledger = put_ledger_that_invalidates  # type: ignore[method-assign]

    from api.analytics.turn_roster import iter_turn_players

    first_player_id = next(iter_turn_players(turn_111)).id
    with pytest.raises(FleetGapFillEpochInvalidated, match="aborted: invalidation generation"):
        get_or_materialize_fleet_snapshot(
            persistence,
            628580,
            1,
            turn_111,
            load_turn=load_turn,
        )

    assert persistence.get_snapshot(628580, 1, 111) is None
    # One coherent attempt bumps generation once via the hooked put -- not N spins.
    assert persistence.invalidation_generation(628580, 1, first_player_id) == 1


def test_gap_fill_succeeds_on_retry_after_invalidation_stops(persistence, load_turn):
    """After epoch abort, a later materialize completes once invalidation stops."""
    from api.errors import FleetGapFillEpochInvalidated

    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    turn_111 = load_turn(111)
    assert turn_111 is not None
    original_put_ledger = persistence.put_ledger
    invalidate_once = {"done": False}

    def put_ledger_invalidate_once(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_id: int,
        persisted,
        **kwargs,
    ) -> None:
        original_put_ledger(
            game_id,
            perspective,
            turn_number,
            player_id,
            persisted,
            **kwargs,
        )
        if not invalidate_once["done"]:
            invalidate_once["done"] = True
            persistence.invalidate_for_turn_write(game_id, perspective, turn_number)

    persistence.put_ledger = put_ledger_invalidate_once  # type: ignore[method-assign]

    with pytest.raises(FleetGapFillEpochInvalidated):
        get_or_materialize_fleet_snapshot(
            persistence,
            628580,
            1,
            turn_111,
            load_turn=load_turn,
        )

    persistence.put_ledger = original_put_ledger  # type: ignore[method-assign]
    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_111,
        load_turn=load_turn,
    )
    assert snapshot.turn == 111
    assert persistence.get_snapshot(628580, 1, 111) is not None


def _put_provenance_final_snapshot(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn,
) -> FleetTurnSnapshot:
    baseline = ensure_fleet_baseline(game_id, perspective, turn)
    for ledger in baseline.players:
        persistence.put_ledger(
            game_id,
            perspective,
            turn.settings.turn,
            ledger.player_id,
            PersistedFleetLedger(
                ledger=ledger,
                provenance=FleetMaterializationProvenance(
                    turn_evidence_at_n=True,
                    prior_ledger_at_n_minus_1=True,
                ),
            ),
        )
    snapshot = persistence.get_snapshot(game_id, perspective, turn.settings.turn)
    assert snapshot is not None
    return snapshot


def _inference_materialization_for_fleet(memory_backend, load_turn):
    from api.analytics.fleet.held_solutions import (
        FleetInferenceMaterialization,
        FleetInferenceSupport,
    )
    from api.analytics.scores.export_services import ScoresExportContext

    inference_persistence = InferenceRowPersistenceService(memory_backend)
    scores_services = ScoresExportContext(persistence=inference_persistence)
    return (
        inference_persistence,
        FleetInferenceMaterialization(
            inference=FleetInferenceSupport(scores_services=scores_services),
            load_turn=load_turn,
        ),
    )


def _seed_scores_rows_for_all_players(
    inference_persistence: InferenceRowPersistenceService,
    turn,
) -> None:
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.analytics.turn_roster import iter_turn_players
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    for player in iter_turn_players(turn):
        inference_persistence.put_row(
            628580,
            1,
            turn.settings.turn,
            player.id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary=f"cached-{player.id}",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
        )


def test_gap_fill_returns_cached_snapshot_when_peer_finished_during_retries(persistence, load_turn):
    """On invalidation abort, return a peer-written final snapshot instead of raising."""
    from api.analytics.fleet.chain import _FleetSnapshotInvalidated

    turn_110 = load_turn(110)
    assert turn_110 is not None
    _put_provenance_final_snapshot(persistence, 628580, 1, turn_110)

    turn_111 = load_turn(111)
    assert turn_111 is not None
    winner = _put_provenance_final_snapshot(persistence, 628580, 1, turn_111)

    with patch(
        "api.analytics.fleet.gap_fill_coordinator._materialize_fleet_ledger_chain_for_player",
        side_effect=_FleetSnapshotInvalidated,
    ):
        result = get_or_materialize_fleet_snapshot(
            persistence,
            628580,
            1,
            turn_111,
            load_turn=load_turn,
        )

    assert result == winner


def test_ensure_fleet_export_returns_false_on_epoch_abort_without_final(
    sample_turn, memory_backend
):
    """Ensure catches epoch abort as unsatisfied; non-final ledger is not ensure-final."""
    from dataclasses import replace

    from api.analytics.export_types import ExportScope
    from api.analytics.fleet.compute_services import resolve_fleet_services, turn_chain_through
    from api.analytics.fleet.exports import (
        EXPORT_CATALOG,
        ensure_fleet_export,
        is_fleet_export_ensure_satisfied,
    )
    from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.errors import FleetGapFillEpochInvalidated
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    from tests.export_chain_test_fixtures import export_chain_query_context
    from tests.scores_exports_helpers import (
        GAME_ID,
        first_player_id,
        perspective,
        put_persisted_row,
    )

    player_id = first_player_id(sample_turn)
    turn_number = 8
    host_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=turn_number),
        game=replace(sample_turn.game, turn=turn_number),
    )
    stored_turns = turn_chain_through(host_turn)
    inference_persistence = InferenceRowPersistenceService(memory_backend)
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
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=turn_number,
        player_id=player_id,
    )

    with patch(
        "api.analytics.fleet.exports.get_or_materialize_fleet_ledger_for_player",
        side_effect=FleetGapFillEpochInvalidated(
            "fleet gap-fill aborted: invalidation generation bumped mid-chain"
        ),
    ):
        assert ensure_fleet_export(ctx, scope) is False

    assert is_fleet_export_ensure_satisfied(ctx, scope) is False
    assert EXPORT_CATALOG.is_ensure_satisfied(ctx, scope) is False

    # Counter-check: a persisted non-final ledger still leaves ensure unsatisfied.
    fleet_services = resolve_fleet_services(ctx)
    player_ledger = ensure_fleet_baseline(GAME_ID, perspective(sample_turn), host_turn).players
    ledger = next(entry for entry in player_ledger if entry.player_id == player_id)
    fleet_services.persistence.put_ledger(
        GAME_ID,
        perspective(sample_turn),
        turn_number,
        player_id,
        PersistedFleetLedger(
            ledger=ledger,
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=False,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )
    assert fleet_services.persistence.has_ledger(
        GAME_ID, perspective(sample_turn), turn_number, player_id
    )
    assert not fleet_services.persistence.has_final_ledger(
        GAME_ID, perspective(sample_turn), turn_number, player_id
    )
    assert is_fleet_export_ensure_satisfied(ctx, scope) is False


def test_put_snapshot_stamps_current_materialization_version(persistence, load_turn):
    turn = load_turn(111)
    assert turn is not None
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    assert snapshot.materialization_version == 0
    persistence.put_snapshot(628580, 1, 111, snapshot)
    assert snapshot.materialization_version == FLEET_MATERIALIZATION_VERSION
    stored = persistence.get_snapshot(628580, 1, 111)
    assert stored is not None
    assert stored.materialization_version == FLEET_MATERIALIZATION_VERSION


def test_stale_materialization_version_is_deleted_on_read(persistence, load_turn, memory_backend):
    turn = load_turn(111)
    assert turn is not None
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    stale_payload = fleet_turn_snapshot_to_json(snapshot)
    ledger_wire = stale_payload[FLEET_LEDGERS_KEY]
    for player_key in ledger_wire:
        player_entry = ledger_wire[player_key]
        if isinstance(player_entry, dict):
            player_entry["materializationVersion"] = FLEET_MATERIALIZATION_VERSION - 1
    memory_backend.put(
        persistence.document_key(628580, 1, 111),
        stale_payload,
    )
    first_player_id = snapshot.players[0].player_id
    generation_before = persistence.invalidation_generation(628580, 1, first_player_id)

    assert persistence.get_snapshot(628580, 1, 111) is None
    assert persistence.has_snapshot(628580, 1, 111) is False
    for player_ledger in snapshot.players:
        assert persistence.invalidation_generation(628580, 1, player_ledger.player_id) == (
            generation_before + 1
        )


def test_missing_materialization_version_is_deleted_on_read(persistence, load_turn, memory_backend):
    from api.analytics.fleet.serialization import fleet_acquisition_ledger_to_json

    turn = load_turn(111)
    assert turn is not None
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    legacy_payload = {
        "analyticId": "fleet",
        "gameId": 628580,
        "perspective": 1,
        "turn": 111,
        "players": [
            fleet_acquisition_ledger_to_json(player_ledger) for player_ledger in snapshot.players
        ],
    }
    memory_backend.put(
        persistence.document_key(628580, 1, 111),
        legacy_payload,
    )

    assert persistence.get_snapshot(628580, 1, 111) is None
    assert persistence.has_snapshot(628580, 1, 111) is False


def test_stale_chain_anchor_skipped_during_gap_fill(persistence, load_turn, memory_backend):
    turn_110 = load_turn(110)
    assert turn_110 is not None
    stale_anchor = ensure_fleet_baseline(628580, 1, turn_110)
    stale_anchor.players[0].records.append(
        FleetShipRecord(record_id="stale-rec", disposition="active"),
    )
    stale_payload = fleet_turn_snapshot_to_json(stale_anchor)
    ledger_wire = stale_payload[FLEET_LEDGERS_KEY]
    for player_key in ledger_wire:
        player_entry = ledger_wire[player_key]
        if isinstance(player_entry, dict):
            player_entry["materializationVersion"] = FLEET_MATERIALIZATION_VERSION - 1
    memory_backend.put(
        persistence.document_key(628580, 1, 110),
        stale_payload,
    )

    turn_112 = load_turn(112)
    assert turn_112 is not None
    snapshot = get_or_materialize_fleet_snapshot(
        persistence,
        628580,
        1,
        turn_112,
        load_turn=load_turn,
    )

    assert snapshot.turn == 112
    assert snapshot.materialization_version == FLEET_MATERIALIZATION_VERSION
    assert all(record.record_id != "stale-rec" for record in snapshot.players[0].records)
    rematerialized_110 = persistence.get_snapshot(628580, 1, 110)
    assert rematerialized_110 is not None
    assert rematerialized_110.materialization_version == FLEET_MATERIALIZATION_VERSION
    assert all(record.record_id != "stale-rec" for record in rematerialized_110.players[0].records)
