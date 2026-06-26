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
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetShipRecord,
    FleetTurnSnapshot,
)
from api.errors import ConflictError, NotFoundError, ValidationError
from api.serialization.turn import turn_info_from_json
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
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
    assert persistence.invalidation_generation(628580, 1) == 0
    cleared = persistence.invalidate_for_turn_write(628580, 1, 111)
    assert cleared == {111, 112}
    assert persistence.invalidation_generation(628580, 1) == 1
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
    assert fleet_persistence.get_snapshot(628580, 1, 111) is None

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

    assert fleet_persistence.get_snapshot(628580, 1, turn_number) is None


def test_gap_fill_aborts_on_concurrent_invalidation(persistence, load_turn, memory_backend):
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
    put_generations: list[int] = []
    original_put_snapshot = persistence.put_snapshot

    def hooked_put_snapshot(*args, **kwargs):
        snapshot = original_put_snapshot(*args, **kwargs)
        put_generations.append(persistence.invalidation_generation(628580, 1))
        if len(put_generations) == 1:
            sync.wait()
            sync.wait()
        return snapshot

    persistence.put_snapshot = hooked_put_snapshot  # type: ignore[method-assign]

    gap_fill_error: BaseException | None = None
    snapshot: FleetTurnSnapshot | None = None

    def run_gap_fill() -> None:
        nonlocal gap_fill_error, snapshot
        try:
            snapshot = get_or_materialize_fleet_snapshot(
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

    assert gap_fill_error is None
    assert snapshot is not None
    assert snapshot.turn == 112
    assert put_generations[0] == 0
    assert put_generations[-2:] == [1, 1]
    assert persistence.get_snapshot(628580, 1, 111) is not None
    assert persistence.get_snapshot(628580, 1, 112) == snapshot
    assert len(snapshot.players[0].records) == 6
    assert snapshot.players[0].records[0].record_id == "gap-rec"


def test_gap_fill_does_not_persist_torn_tail_after_mid_chain_invalidation(persistence, load_turn):
    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_112 = load_turn(112)
    assert turn_112 is not None
    sync = threading.Barrier(2)
    attempt_puts: list[list[int]] = []
    current_attempt_puts: list[int] = []
    mid_chain_intercepted = False
    original_put_snapshot = persistence.put_snapshot

    def hooked_put_snapshot(
        game_id: int,
        perspective: int,
        turn_number: int,
        snapshot: FleetTurnSnapshot,
    ) -> None:
        nonlocal mid_chain_intercepted
        original_put_snapshot(game_id, perspective, turn_number, snapshot)
        current_attempt_puts.append(turn_number)
        if turn_number == 111 and not mid_chain_intercepted:
            mid_chain_intercepted = True
            assert persistence.get_snapshot(628580, 1, 112) is None
            sync.wait()
            persistence.invalidate_for_turn_write(628580, 1, 111)
            assert persistence.get_snapshot(628580, 1, 112) is None
            attempt_puts.append(list(current_attempt_puts))
            current_attempt_puts.clear()
            sync.wait()

    persistence.put_snapshot = hooked_put_snapshot  # type: ignore[method-assign]

    gap_fill_error: BaseException | None = None
    snapshot: FleetTurnSnapshot | None = None

    def run_gap_fill() -> None:
        nonlocal gap_fill_error, snapshot
        try:
            snapshot = get_or_materialize_fleet_snapshot(
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
    sync.wait()
    gap_fill_thread.join()

    assert gap_fill_error is None
    assert snapshot is not None
    assert attempt_puts[0] == [111]
    assert snapshot.turn == 112
    assert persistence.get_snapshot(628580, 1, 112) == snapshot


def test_gap_fill_raises_conflict_after_max_invalidation_retries(persistence, load_turn):
    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_111 = load_turn(111)
    assert turn_111 is not None
    original_put_snapshot = persistence.put_snapshot

    def put_snapshot_that_invalidates(
        game_id: int,
        perspective: int,
        turn_number: int,
        snapshot: FleetTurnSnapshot,
    ) -> None:
        original_put_snapshot(game_id, perspective, turn_number, snapshot)
        persistence.invalidate_for_turn_write(game_id, perspective, turn_number)

    persistence.put_snapshot = put_snapshot_that_invalidates  # type: ignore[method-assign]

    with patch("api.analytics.fleet.chain.GAP_FILL_MAX_RETRIES", 3):
        with pytest.raises(ConflictError, match="exceeded 3 invalidation retries"):
            get_or_materialize_fleet_snapshot(
                persistence,
                628580,
                1,
                turn_111,
                load_turn=load_turn,
            )

    assert persistence.get_snapshot(628580, 1, 111) is None
    assert persistence.invalidation_generation(628580, 1) == 3
