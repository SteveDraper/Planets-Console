"""Tests for fleet inferred acquisition from scores held solutions."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.chain import apply_fleet_turn_delta, ensure_fleet_baseline
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization, FleetInferenceSupport
from api.analytics.fleet.inferred_acquisition_ingest import ingest_turn_inferred_acquisitions
from api.analytics.fleet.serialization import fleet_turn_snapshot_to_compute_wire
from api.analytics.fleet.types import (
    FleetFieldUnknown,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.models import InferenceSolutionAction
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.export_services import ScoresExportContext
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.fleet_fixtures import ledger_for_player, single_ship_turn
from tests.scores_exports_helpers import (
    inference_solution,
    perspective,
    schedule_row_with_ladder,
    ship_build_domain,
    ship_build_wire,
)


def _turn_with_score_delta(
    *,
    turn_number: int,
    owner_id: int,
    shipchange: int = 0,
    freighterchange: int = 0,
):
    turn = single_ship_turn(turn_number=turn_number, ship_id=1, owner_id=owner_id, x=100, y=100)
    turn = replace(turn, ships=[])
    score = replace(
        turn.scores[0],
        turn=turn_number,
        ownerid=owner_id,
        shipchange=shipchange,
        freighterchange=freighterchange,
    )
    return replace(turn, scores=[score])


def _inference_materialization(
    inference: FleetInferenceSupport,
    turn,
) -> FleetInferenceMaterialization:
    return FleetInferenceMaterialization(
        inference=inference,
        load_turn=lambda _turn_number: turn,
    )


def test_positive_warship_delta_creates_two_placeholder_rows():
    turn = _turn_with_score_delta(turn_number=5, owner_id=8, shipchange=2)
    snapshot = ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
    )

    ledger = ledger_for_player(snapshot, 8)
    assert len(ledger.records) == 2
    for record in ledger.records:
        assert record.disposition == "active"
        assert record.fields.ship_id == FleetFieldUnknown()
        assert record.fields.hull == FleetFieldUnknown()
        assert record.fields.engine == FleetFieldUnknown()
        assert record.build_option_sets == []
        assert record.events[0].kind == "scoreboard_delta"
        assert record.events[0].payload["warshipDelta"] == 2
        assert record.events[0].payload["shipClass"] == "warship"


def test_positive_freighter_delta_creates_two_placeholder_rows():
    turn = _turn_with_score_delta(turn_number=5, owner_id=8, freighterchange=2)
    snapshot = ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
    )

    ledger = ledger_for_player(snapshot, 8)
    assert len(ledger.records) == 2
    for record in ledger.records:
        assert record.disposition == "active"
        assert record.fields.ship_id == FleetFieldUnknown()
        assert record.fields.hull == FleetFieldUnknown()
        assert record.fields.engine == FleetFieldUnknown()
        assert record.build_option_sets == []
        assert record.events[0].kind == "scoreboard_delta"
        assert record.events[0].payload["warshipDelta"] == 0
        assert record.events[0].payload["freighterDelta"] == 2
        assert record.events[0].payload["shipClass"] == "freighter"


def test_placeholder_rows_remain_unknown_when_inference_in_progress_with_no_solutions():
    turn = _turn_with_score_delta(turn_number=5, owner_id=8, shipchange=2)
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
        inference_materialization=_inference_materialization(
            FleetInferenceSupport(
                scores_services=ScoresExportContext(
                    persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
                ),
            ),
            turn,
        ),
    )

    ledger = ledger_for_player(snapshot, 8)
    assert len(ledger.records) == 2
    assert all(record.build_option_sets == [] for record in ledger.records)
    assert all(record.fields.hull == FleetFieldUnknown() for record in ledger.records)


def test_streaming_refine_updates_option_sets(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    turn = replace(
        sample_turn,
        ships=[],
        scores=[
            replace(
                score,
                turn=sample_turn.settings.turn,
                ownerid=player_id,
                shipchange=2,
                freighterchange=0,
            )
            for score in sample_turn.scores
            if score.ownerid == player_id
        ],
    )
    schedule_row_with_ladder(
        scheduler,
        turn,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=90,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-a",
                        label="Cruiser A",
                        hull_id=13,
                        engine_id=9,
                    ),
                    ship_build_domain(
                        combo_id="combo-a",
                        label="Cruiser A",
                        hull_id=13,
                        engine_id=9,
                        count=1,
                    ),
                ),
            ),
            inference_solution(
                objective_value=70,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-b",
                        label="Destroyer B",
                        hull_id=9,
                        engine_id=5,
                    ),
                    ship_build_domain(
                        combo_id="combo-c",
                        label="Cruiser C",
                        hull_id=13,
                        engine_id=7,
                    ),
                ),
            ),
        ],
    )
    inference = FleetInferenceSupport(
        scores_services=ScoresExportContext(
            persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            scheduler=scheduler,
        ),
    )
    baseline = ensure_fleet_baseline(628580, perspective(turn), turn)
    snapshot = ingest_turn_inferred_acquisitions(
        baseline,
        turn,
    )
    ledger = ledger_for_player(snapshot, player_id)
    assert all(record.build_option_sets == [] for record in ledger.records)

    refined = ingest_turn_inferred_acquisitions(
        snapshot,
        turn,
        inference_materialization=_inference_materialization(inference, turn),
    )

    records = ledger_for_player(refined, player_id).records
    assert len(records) == 2
    assert records[0].build_option_sets[0].combo_id == "combo-a"
    assert records[0].build_option_sets[1].combo_id == "combo-b"
    assert records[1].build_option_sets[0].combo_id == "combo-a"
    assert records[1].build_option_sets[1].combo_id == "combo-c"
    assert records[0].display_default_option_set_index == 0
    assert records[0].fields.hull == FleetFieldUnknown()
    assert any(event.kind == "inference_update" for event in records[0].events)


def test_streaming_refine_updates_freighter_option_sets(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    turn = replace(
        sample_turn,
        ships=[],
        scores=[
            replace(
                score,
                turn=sample_turn.settings.turn,
                ownerid=player_id,
                shipchange=0,
                freighterchange=2,
            )
            for score in sample_turn.scores
            if score.ownerid == player_id
        ],
    )
    schedule_row_with_ladder(
        scheduler,
        turn,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=90,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo_freighter",
                        label="Freighter",
                        hull_id=15,
                        engine_id=1,
                    ),
                    ship_build_domain(
                        combo_id="combo_freighter",
                        label="Freighter",
                        hull_id=15,
                        engine_id=1,
                        count=1,
                    ),
                ),
            ),
            inference_solution(
                objective_value=70,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo_freighter",
                        label="Freighter",
                        hull_id=15,
                        engine_id=1,
                    ),
                ),
            ),
        ],
    )
    inference = FleetInferenceSupport(
        scores_services=ScoresExportContext(
            persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            scheduler=scheduler,
        ),
    )
    baseline = ensure_fleet_baseline(628580, perspective(turn), turn)
    snapshot = ingest_turn_inferred_acquisitions(
        baseline,
        turn,
    )
    ledger = ledger_for_player(snapshot, player_id)
    assert all(record.build_option_sets == [] for record in ledger.records)

    refined = ingest_turn_inferred_acquisitions(
        snapshot,
        turn,
        inference_materialization=_inference_materialization(inference, turn),
    )

    records = ledger_for_player(refined, player_id).records
    assert len(records) == 2
    for record in records:
        assert len(record.build_option_sets) == 1
        assert record.build_option_sets[0].combo_id == "combo_freighter"
        assert record.build_option_sets[0].hull_id == 15
        assert record.display_default_option_set_index == 0
        assert record.fields.hull == FleetFieldUnknown()
        assert any(event.kind == "inference_update" for event in record.events)


def test_persisted_inference_refines_placeholders():
    turn = _turn_with_score_delta(turn_number=111, owner_id=8, shipchange=1)
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_row(
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
                            count=1,
                        )
                    ],
                }
            ],
        ),
    )
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
        inference_materialization=_inference_materialization(
            FleetInferenceSupport(scores_services=ScoresExportContext(persistence=persistence)),
            turn,
        ),
    )

    record = ledger_for_player(snapshot, 8).records[0]
    assert len(record.build_option_sets) == 1
    assert record.build_option_sets[0].hull_id == 13
    assert record.build_option_sets[0].engine_id == 9
    assert record.fields.hull == FleetFieldUnknown()


def test_persisted_inference_refines_freighter_placeholders():
    turn = _turn_with_score_delta(turn_number=111, owner_id=8, freighterchange=1)
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="one freighter",
            solution_count=1,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 55,
                    "actions": [],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="combo_freighter",
                            label="Freighter",
                            hull_id=15,
                            engine_id=1,
                            count=1,
                        )
                    ],
                }
            ],
        ),
    )
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
        inference_materialization=_inference_materialization(
            FleetInferenceSupport(scores_services=ScoresExportContext(persistence=persistence)),
            turn,
        ),
    )

    record = ledger_for_player(snapshot, 8).records[0]
    assert len(record.build_option_sets) == 1
    assert record.build_option_sets[0].combo_id == "combo_freighter"
    assert record.build_option_sets[0].hull_id == 15
    assert record.build_option_sets[0].engine_id == 1
    assert record.fields.hull == FleetFieldUnknown()


def test_duplicate_combo_id_keeps_highest_solution_rank_weight():
    turn = _turn_with_score_delta(turn_number=5, owner_id=8, shipchange=1)
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_row(
        628580,
        1,
        5,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="same combo different ranks",
            solution_count=2,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 40,
                    "actions": [],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="combo-13",
                            label="Cruiser",
                            hull_id=13,
                            engine_id=9,
                        )
                    ],
                },
                {
                    "objectiveValue": 90,
                    "actions": [],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="combo-13",
                            label="Cruiser",
                            hull_id=13,
                            engine_id=9,
                        )
                    ],
                },
            ],
        ),
    )
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
        inference_materialization=_inference_materialization(
            FleetInferenceSupport(scores_services=ScoresExportContext(persistence=persistence)),
            turn,
        ),
    )

    record = ledger_for_player(snapshot, 8).records[0]
    assert len(record.build_option_sets) == 1
    assert record.build_option_sets[0].solution_rank_weight == 90
    assert record.display_default_option_set_index == 0


def test_wire_output_uses_consistent_option_set_tuples_not_field_cartesian_product():
    turn = _turn_with_score_delta(turn_number=5, owner_id=8, shipchange=1)
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_row(
        628580,
        1,
        5,
        8,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="ambiguous hull",
            solution_count=2,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 80,
                    "actions": [],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="combo-cruiser",
                            label="Cruiser",
                            hull_id=13,
                            engine_id=9,
                        )
                    ],
                },
                {
                    "objectiveValue": 60,
                    "actions": [],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="combo-destroyer",
                            label="Destroyer",
                            hull_id=9,
                            engine_id=5,
                        )
                    ],
                },
            ],
        ),
    )
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
        inference_materialization=_inference_materialization(
            FleetInferenceSupport(scores_services=ScoresExportContext(persistence=persistence)),
            turn,
        ),
    )

    wire = fleet_turn_snapshot_to_compute_wire(snapshot)
    record_wire = wire["players"][0]["records"][0]
    assert "buildOptionSets" in record_wire
    assert len(record_wire["buildOptionSets"]) == 2
    assert record_wire["fields"]["hull"]["kind"] == "unknown"
    assert record_wire["fields"]["engine"]["kind"] == "unknown"
    assert not any(
        field.get("kind") == "options"
        for field in record_wire["fields"].values()
        if isinstance(field, dict)
    )
    option_sets = record_wire["buildOptionSets"]
    assert {entry["hullId"] for entry in option_sets} == {13, 9}
    assert all("beamCount" in entry and "launcherCount" in entry for entry in option_sets)


def test_ephemeral_compute_services_refine_from_scheduler(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    turn = replace(
        sample_turn,
        ships=[],
        scores=[
            replace(
                score,
                turn=sample_turn.settings.turn,
                ownerid=player_id,
                shipchange=1,
                freighterchange=0,
            )
            for score in sample_turn.scores
            if score.ownerid == player_id
        ],
    )
    schedule_row_with_ladder(
        scheduler,
        turn,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=40,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense_posts_added_total",
                        label="Planet defense",
                        count=1,
                    ),
                ),
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-13",
                        label="Cruiser",
                        hull_id=13,
                        engine_id=9,
                    ),
                ),
            )
        ],
    )
    from api.analytics.compute_context import invoke_analytic_compute
    from api.analytics.fleet import ANALYTIC_ID, compute_fleet

    services = build_ephemeral_fleet_compute_services(
        turn,
        perspective=perspective(turn),
        inference=FleetInferenceSupport(
            scores_services=ScoresExportContext(
                persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
                scheduler=scheduler,
            ),
        ),
    )
    payload = invoke_analytic_compute(
        compute_fleet,
        turn,
        export_services={ANALYTIC_ID: services},
    )
    record = next(
        rec
        for player in payload["players"]
        for rec in player["records"]
        if player["playerId"] == player_id
    )
    assert record["buildOptionSets"][0]["hullId"] == 13
