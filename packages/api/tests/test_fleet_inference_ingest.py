"""Tests for fleet inferred acquisition from scores held solutions."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.chain import apply_fleet_turn_delta, ensure_fleet_baseline
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization, FleetInferenceSupport
from api.analytics.fleet.inferred_acquisition_ingest import ingest_turn_inferred_acquisitions
from api.analytics.fleet.observation_ingest import ingest_turn_ship_observations
from api.analytics.fleet.serialization import (
    fleet_ship_record_from_json,
    fleet_ship_record_to_json,
    fleet_turn_snapshot_to_compute_wire,
)
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldBounded,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.analytic import infer_military_score_build
from api.analytics.military_score_inference.host_turn_targets import (
    host_turn_targets_from_wire_event,
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
from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

from tests.fleet_fixtures import ledger_for_player, single_ship_turn
from tests.inference_corpus.fixtures import load_turn_fixture
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


def test_refine_preserves_scoreboard_ship_id_bounds(sample_turn):
    """Option-set refine must not clear id bounds already applied by observation ingest.

    Persist phase-2 refine runs after materialize has tightened ``lte`` bounds; wiping
    them left intermediate-turn rows as ``?`` while unreined same-turn rows kept bounds.
    """
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
                capitalships=10,
                freighters=5,
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
        ],
    )
    inference = FleetInferenceSupport(
        scores_services=ScoresExportContext(
            persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            scheduler=scheduler,
        ),
    )
    bounded = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, perspective(turn), turn),
        turn,
    )
    before = ledger_for_player(bounded, player_id).records
    assert len(before) == 2
    bounds_before = [_ship_id_lte_bound(record) for record in before]
    assert all(bound is not None for bound in bounds_before)

    refined = ingest_turn_inferred_acquisitions(
        bounded,
        turn,
        inference_materialization=_inference_materialization(inference, turn),
    )
    after = ledger_for_player(refined, player_id).records
    assert len(after) == 2
    assert all(len(record.build_option_sets) > 0 for record in after)
    assert [_ship_id_lte_bound(record) for record in after] == bounds_before
    assert all(isinstance(record.fields.hull, FleetFieldUnknown) for record in after)


def test_refine_preserves_full_information_observation_option_set(sample_turn):
    """Own-perspective sighting locks confirmed fit; phase-2 refine must not replace it."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = 8
    turn_number = sample_turn.settings.turn
    turn = single_ship_turn(
        turn_number=turn_number,
        ship_id=3,
        owner_id=player_id,
        x=200,
        y=200,
        hull_id=13,
        engine_id=9,
        beam_id=3,
        torpedoid=6,
    )
    turn = replace(
        turn,
        scores=[
            replace(
                score,
                turn=turn_number,
                ownerid=player_id,
                capitalships=10,
                freighters=5,
                shipchange=1,
                freighterchange=0,
            )
            for score in turn.scores
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
                        combo_id="combo-inferred",
                        label="Wrong fit",
                        hull_id=99,
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
    # Full information: perspective == ship owner. Seed a bounded placeholder the
    # sighting will absorb (requires lock-compatible option sets for arbitration).
    snapshot = ensure_fleet_baseline(628580, player_id, turn)
    ledger_for_player(snapshot, player_id).records.append(
        FleetShipRecord(
            record_id="matched-placeholder",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=5),
                built_turn=FleetFieldKnown(turn_number),
            ),
            build_option_sets=[
                FleetBuildOptionSet(
                    hull_id=13,
                    engine_id=9,
                    beam_id=3,
                    torp_id=6,
                    beam_count=8,
                    launcher_count=6,
                    solution_rank_weight=10,
                )
            ],
            events=[
                FleetEvidenceEvent(
                    event_id="evt-acq",
                    kind="scoreboard_delta",
                    turn=turn_number,
                    source="scoreboard",
                    payload={
                        "shipClass": "warship",
                        "warshipDelta": 1,
                        "freighterDelta": 0,
                    },
                )
            ],
        )
    )
    observed_snapshot = ingest_turn_ship_observations(snapshot, turn)
    record = ledger_for_player(observed_snapshot, player_id).records[0]
    assert record.record_id == "matched-placeholder"
    assert record.build_option_sets == [
        FleetBuildOptionSet(
            hull_id=13,
            engine_id=9,
            beam_id=3,
            torp_id=6,
            beam_count=8,
            launcher_count=6,
        )
    ]
    confirmed = list(record.build_option_sets)

    refined = ingest_turn_inferred_acquisitions(
        observed_snapshot,
        turn,
        inference_materialization=_inference_materialization(inference, turn),
    )
    after = ledger_for_player(refined, player_id).records[0]
    assert after.build_option_sets == confirmed
    assert after.fields.hull == FleetFieldKnown(value=13)
    assert after.fields.engine == FleetFieldKnown(value=9)
    assert after.fields.beams == FleetFieldKnown(value=3)
    assert after.fields.launchers == FleetFieldKnown(value=6)
    assert not any(event.kind == "inference_update" for event in after.events)


def test_refine_preserves_partial_observation_hull_and_fills_unknown_axes(sample_turn):
    """Foreign fog sighting locks hull only; refine may attach inferred fits for other axes."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = 8
    perspective_id = 1
    turn_number = sample_turn.settings.turn
    fog_ship_turn = single_ship_turn(
        turn_number=turn_number,
        ship_id=3,
        owner_id=player_id,
        x=200,
        y=200,
        hull_id=13,
    )
    fog_ship = replace(
        fog_ship_turn.ships[0],
        beams=0,
        beamid=0,
        torps=0,
        torpedoid=0,
        bays=0,
        engineid=0,
    )
    # Make the logged-in perspective a different player than the ship owner so
    # observation is partial, while keeping owner 8 on the turn roster.
    perspective_player = next(p for p in fog_ship_turn.players if p.id == perspective_id)
    owner_player = fog_ship_turn.player
    turn = replace(
        fog_ship_turn,
        player=perspective_player,
        players=[
            owner_player,
            *[p for p in fog_ship_turn.players if p.id != perspective_id],
        ],
        ships=[fog_ship],
        scores=[
            replace(
                score,
                turn=turn_number,
                ownerid=player_id,
                capitalships=10,
                freighters=5,
                shipchange=1,
                freighterchange=0,
            )
            for score in fog_ship_turn.scores
            if score.ownerid == player_id
        ],
    )
    assert perspective(turn) == perspective_id
    assert perspective_id != player_id
    schedule_row_with_ladder(
        scheduler,
        turn,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=90,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-inferred",
                        label="Inferred fit",
                        hull_id=13,
                        engine_id=9,
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
    snapshot = ensure_fleet_baseline(628580, perspective_id, turn)
    ledger_for_player(snapshot, player_id).records.append(
        FleetShipRecord(
            record_id="matched-placeholder",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=5),
                built_turn=FleetFieldKnown(turn_number),
            ),
            build_option_sets=[
                FleetBuildOptionSet(hull_id=13, solution_rank_weight=10),
            ],
            events=[
                FleetEvidenceEvent(
                    event_id="evt-acq",
                    kind="scoreboard_delta",
                    turn=turn_number,
                    source="scoreboard",
                    payload={
                        "shipClass": "warship",
                        "warshipDelta": 1,
                        "freighterDelta": 0,
                    },
                )
            ],
        )
    )
    observed_snapshot = ingest_turn_ship_observations(snapshot, turn)
    before = ledger_for_player(observed_snapshot, player_id).records[0]
    assert before.record_id == "matched-placeholder"
    assert before.fields.hull == FleetFieldKnown(value=13)
    assert before.fields.engine == FleetFieldUnknown()
    assert before.fields.beams == FleetFieldUnknown()
    assert before.fields.launchers == FleetFieldUnknown()

    refined = ingest_turn_inferred_acquisitions(
        observed_snapshot,
        turn,
        inference_materialization=_inference_materialization(inference, turn),
    )
    after = ledger_for_player(refined, player_id).records[0]
    assert after.fields.hull == FleetFieldKnown(value=13)
    assert after.fields.engine == FleetFieldUnknown()
    assert len(after.build_option_sets) >= 1
    assert after.build_option_sets[0].hull_id == 13
    assert after.build_option_sets[0].combo_id == "combo-inferred"
    assert after.build_option_sets[0].engine_id == 9
    assert any(event.kind == "inference_update" for event in after.events)


def test_refine_drops_option_sets_for_hulls_other_than_observed(sample_turn):
    """Fog-known hull must not inherit foreign inference fits (Falcon←DSS fingerprint)."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = 8
    perspective_id = 1
    turn_number = sample_turn.settings.turn
    fog_ship_turn = single_ship_turn(
        turn_number=turn_number,
        ship_id=10,
        owner_id=player_id,
        x=200,
        y=200,
        hull_id=87,
    )
    fog_ship = replace(
        fog_ship_turn.ships[0],
        beams=0,
        beamid=0,
        torps=0,
        torpedoid=0,
        bays=0,
        engineid=0,
    )
    perspective_player = next(p for p in fog_ship_turn.players if p.id == perspective_id)
    owner_player = fog_ship_turn.player
    turn = replace(
        fog_ship_turn,
        player=perspective_player,
        players=[
            owner_player,
            *[p for p in fog_ship_turn.players if p.id != perspective_id],
        ],
        ships=[fog_ship],
        scores=[
            replace(
                score,
                turn=turn_number,
                ownerid=player_id,
                capitalships=10,
                freighters=5,
                shipchange=1,
                freighterchange=0,
            )
            for score in fog_ship_turn.scores
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
                        combo_id="combo_91_7_2_none_4_0",
                        label="Build Deep Space Scout: 1x Quantam Drive 7, 4x X-Ray Laser",
                        hull_id=91,
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
    snapshot = ensure_fleet_baseline(628580, perspective_id, turn)
    ledger_for_player(snapshot, player_id).records.append(
        FleetShipRecord(
            record_id="matched-placeholder",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=15),
                built_turn=FleetFieldKnown(turn_number),
            ),
            build_option_sets=[
                FleetBuildOptionSet(hull_id=87),
            ],
            events=[
                FleetEvidenceEvent(
                    event_id="evt-acq",
                    kind="scoreboard_delta",
                    turn=turn_number,
                    source="scoreboard",
                    payload={
                        "shipClass": "warship",
                        "warshipDelta": 1,
                        "freighterDelta": 0,
                    },
                )
            ],
        )
    )
    observed_snapshot = ingest_turn_ship_observations(snapshot, turn)
    before = ledger_for_player(observed_snapshot, player_id).records[0]
    assert before.fields.hull == FleetFieldKnown(value=87)
    hull_only_prior = [
        FleetBuildOptionSet(
            hull_id=87,
            engine_id=None,
            beam_id=None,
            torp_id=None,
            beam_count=None,
            launcher_count=None,
        )
    ]
    assert before.build_option_sets == hull_only_prior
    assert before.display_default_option_set_index == 0

    refined = ingest_turn_inferred_acquisitions(
        observed_snapshot,
        turn,
        inference_materialization=_inference_materialization(inference, turn),
    )
    after = ledger_for_player(refined, player_id).records[0]
    assert after.fields.hull == FleetFieldKnown(value=87)
    # Foreign DSS candidates were lock-filtered out; keep observation hull-only
    # seed instead of assigning [] (and never stamp Falcon onto DSS slot fills).
    assert after.build_option_sets == hull_only_prior
    assert after.display_default_option_set_index == 0
    assert all(option.hull_id == 87 for option in after.build_option_sets)
    assert all(option.engine_id is None for option in after.build_option_sets)
    restored = fleet_ship_record_from_json(fleet_ship_record_to_json(after))
    assert restored.build_option_sets == hull_only_prior
    assert restored.display_default_option_set_index == 0


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
    turn = _turn_with_score_delta(
        turn_number=5,
        owner_id=player_id,
        shipchange=1,
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
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID

    scores_services = ScoresExportContext(
        persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        scheduler=scheduler,
    )
    services = build_ephemeral_fleet_compute_services(
        turn,
        perspective=perspective(turn),
        inference=FleetInferenceSupport(scores_services=scores_services),
    )
    payload = invoke_analytic_compute(
        compute_fleet,
        turn,
        load_turn=services.load_turn,
        export_services={
            SCORES_ANALYTIC_ID: scores_services,
            ANALYTIC_ID: services,
        },
    )
    record = next(
        rec
        for player in payload["players"]
        for rec in player["records"]
        if player["playerId"] == player_id
    )
    assert record["buildOptionSets"][0]["hullId"] == 13


def test_generic_freighter_option_set_omits_zero_component_ids_on_wire():
    """Generic freighter keeps hullId 0 sentinel; other zero component ids stay omitted."""
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
                    "objectiveValue": 0,
                    "actions": [],
                    "shipBuilds": [
                        {
                            "comboId": "combo_freighter",
                            "label": "Freighter",
                            "count": 1,
                            "hullId": 0,
                            "engineId": 0,
                            "beamCount": 0,
                            "launcherCount": 0,
                        }
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
    assert record.build_option_sets[0].combo_id == "combo_freighter"
    assert record.build_option_sets[0].hull_id == 0
    assert record.build_option_sets[0].engine_id is None

    wire = fleet_turn_snapshot_to_compute_wire(snapshot)
    option_set = wire["players"][0]["records"][0]["buildOptionSets"][0]
    assert option_set["label"] == "Freighter"
    assert option_set["hullId"] == 0
    assert "engineId" not in option_set


def _known_built_turn(record) -> int | None:
    built_turn = record.fields.built_turn
    if isinstance(built_turn, FleetFieldKnown) and isinstance(built_turn.value, int):
        return built_turn.value
    return None


def _inferred_warship_rows(ledger, *, shell_turn: int):
    return [
        record
        for record in ledger.records
        if record.disposition == "active"
        and any(
            event.kind == "scoreboard_delta"
            and event.turn == shell_turn
            and event.payload.get("shipClass") == "warship"
            for event in record.events
        )
    ]


def _inferred_freighter_rows(ledger, *, shell_turn: int):
    return [
        record
        for record in ledger.records
        if record.disposition == "active"
        and any(
            event.kind == "scoreboard_delta"
            and event.turn == shell_turn
            and event.payload.get("shipClass") == "freighter"
            for event in record.events
        )
    ]


def _homeworld_starting_freighter_rows(ledger, *, shell_turn: int):
    return [
        record
        for record in _inferred_freighter_rows(ledger, shell_turn=shell_turn)
        if any(
            event.kind == "scoreboard_delta"
            and event.payload.get("homeworldStartingInventory") is True
            for event in record.events
        )
    ]


def _ship_id_lte_bound(record) -> int | None:
    ship_id = record.fields.ship_id
    if isinstance(ship_id, FleetFieldBounded) and ship_id.operator == "lte":
        return ship_id.value
    return None


def test_accelerated_first_reliable_turn_creates_segment_placeholders_for_root():
    turn = load_turn_fixture("628580/1/turns/3.json")
    player_id = 11
    snapshot = ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
    )

    ledger = ledger_for_player(snapshot, player_id)
    warship_rows = _inferred_warship_rows(ledger, shell_turn=3)
    assert len(warship_rows) == 2
    assert sorted(_known_built_turn(record) for record in warship_rows) == [1, 2]
    for record in warship_rows:
        event = next(event for event in record.events if event.kind == "scoreboard_delta")
        assert event.payload["acceleratedIngest"] is True
        assert event.payload["segmentHostTurn"] == _known_built_turn(record)


def test_accelerated_first_reliable_refines_segment_option_sets_for_root():
    turn = load_turn_fixture("628580/1/turns/3.json")
    player_id = 11
    score = next(entry for entry in turn.scores if entry.ownerid == player_id)
    inference_payload = infer_military_score_build(score, turn)
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    # Put may still receive wire diagnostics; persistence must promote accelerated
    # segments to host_turn_targets and drop the catalog before writing.
    persistence.put_row(
        628580,
        1,
        3,
        player_id,
        PersistedInferenceRow(
            status=str(inference_payload["status"]),
            summary=str(inference_payload["summary"]),
            solution_count=int(inference_payload["solutionCount"]),
            is_complete=True,
            solutions=inference_payload["solutions"],
            diagnostics=inference_payload["diagnostics"],
        ),
    )
    stored = persistence.get_row(628580, 1, 3, player_id)
    assert stored is not None
    assert stored.diagnostics is None
    assert stored.host_turn_targets
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
        inference_materialization=_inference_materialization(
            FleetInferenceSupport(scores_services=ScoresExportContext(persistence=persistence)),
            turn,
        ),
    )

    ledger = ledger_for_player(snapshot, player_id)
    warship_rows = _inferred_warship_rows(ledger, shell_turn=3)
    assert len(warship_rows) == 2
    # Rank-1 Cobol twin for military change 2258 remains after the ladder continues
    # past collision_hull_widen (ship-only early-stop is deferred until after high-prior
    # aggregates; #256). Option sets may include later exacts beyond the twin pair.
    expected_primary = "combo_96_9_5_6_4_2"
    for record in warship_rows:
        combo_ids = {option.combo_id for option in record.build_option_sets}
        assert expected_primary in combo_ids
        assert record.build_option_sets[0].combo_id == expected_primary
        inference_event = next(event for event in record.events if event.kind == "inference_update")
        assert inference_event.payload["acceleratedIngest"] is True
        assert inference_event.payload["segmentHostTurn"] == _known_built_turn(record)


def test_accelerated_first_reliable_refines_without_scores_diagnostics():
    turn = load_turn_fixture("628580/1/turns/3.json")
    player_id = 11
    score = next(entry for entry in turn.scores if entry.ownerid == player_id)
    inference_payload = infer_military_score_build(score, turn)
    wire_complete = inference_api_payload_to_wire_complete(inference_payload)
    host_turn_targets = list(host_turn_targets_from_wire_event(wire_complete))
    assert host_turn_targets
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_row(
        628580,
        1,
        3,
        player_id,
        PersistedInferenceRow(
            status=str(inference_payload["status"]),
            summary=str(inference_payload["summary"]),
            solution_count=int(inference_payload["solutionCount"]),
            is_complete=True,
            solutions=inference_payload["solutions"],
            diagnostics=None,
            host_turn_targets=host_turn_targets,
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

    ledger = ledger_for_player(snapshot, player_id)
    warship_rows = _inferred_warship_rows(ledger, shell_turn=3)
    assert len(warship_rows) == 2
    # Rank-1 Cobol twin for military change 2258 remains after the ladder continues
    # past collision_hull_widen (ship-only early-stop is deferred until after high-prior
    # aggregates; #256). Option sets may include later exacts beyond the twin pair.
    expected_primary = "combo_96_9_5_6_4_2"
    for record in warship_rows:
        combo_ids = {option.combo_id for option in record.build_option_sets}
        assert expected_primary in combo_ids
        assert record.build_option_sets[0].combo_id == expected_primary


def test_accelerated_window_refine_when_intermediate_scoreboard_turn_missing():
    """680224 shape: turn 2 absent; refine builtTurn=1 from scores@3 hostTurnTargets."""
    turn = load_turn_fixture("628580/1/turns/3.json")
    player_id = 2
    score = next(entry for entry in turn.scores if entry.ownerid == player_id)
    inference_payload = infer_military_score_build(score, turn)
    wire_complete = inference_api_payload_to_wire_complete(inference_payload)
    host_turn_targets = list(host_turn_targets_from_wire_event(wire_complete))
    assert host_turn_targets
    assert any(target.host_turn == 1 for target in host_turn_targets)

    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_row(
        628580,
        1,
        3,
        player_id,
        PersistedInferenceRow(
            status=str(inference_payload["status"]),
            summary=str(inference_payload["summary"]),
            solution_count=int(inference_payload["solutionCount"]),
            is_complete=True,
            solutions=inference_payload["solutions"],
            diagnostics=None,
            host_turn_targets=host_turn_targets,
        ),
    )

    def load_turn(turn_number: int):
        # Mid-accelerated storage: first reliable turn present, unreliable turn 2 absent.
        if turn_number == 3:
            return turn
        return None

    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
        inference_materialization=FleetInferenceMaterialization(
            inference=FleetInferenceSupport(
                scores_services=ScoresExportContext(persistence=persistence)
            ),
            load_turn=load_turn,
        ),
    )

    ledger = ledger_for_player(snapshot, player_id)
    starting_rows = _homeworld_starting_freighter_rows(ledger, shell_turn=3)
    window_row = next(
        record
        for record in _inferred_freighter_rows(ledger, shell_turn=3)
        if record not in starting_rows and _known_built_turn(record) == 1
    )
    assert window_row.build_option_sets
    assert window_row.build_option_sets[0].combo_id == "combo_freighter"
    assert window_row.build_option_sets[0].label == "Freighter"
    inference_event = next(event for event in window_row.events if event.kind == "inference_update")
    assert inference_event.payload["acceleratedIngest"] is True
    assert inference_event.payload["segmentHostTurn"] == 1


def test_accelerated_first_reliable_window_freighter_placeholder():
    turn = load_turn_fixture("628580/1/turns/3.json")
    player_id = 2
    snapshot = ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
    )

    ledger = ledger_for_player(snapshot, player_id)
    freighter_rows = _inferred_freighter_rows(ledger, shell_turn=3)
    assert len(freighter_rows) == 3
    starting_rows = _homeworld_starting_freighter_rows(ledger, shell_turn=3)
    assert len(starting_rows) == 1
    window_row = next(
        record
        for record in freighter_rows
        if record not in starting_rows and _known_built_turn(record) == 1
    )
    assert _known_built_turn(window_row) == 1


def test_accelerated_first_reliable_privateer_starting_freighter_and_id_bounds():
    turn = load_turn_fixture("628580/1/turns/3.json")
    player_id = 5
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
    )

    ledger = ledger_for_player(snapshot, player_id)
    starting_rows = _homeworld_starting_freighter_rows(ledger, shell_turn=3)
    assert len(starting_rows) == 1
    assert _ship_id_lte_bound(starting_rows[0]) == 11

    freighter_rows = [
        record
        for record in _inferred_freighter_rows(ledger, shell_turn=3)
        if record not in starting_rows
    ]
    assert len(freighter_rows) == 1
    assert _known_built_turn(freighter_rows[0]) == 1
    assert _ship_id_lte_bound(freighter_rows[0]) == 22

    warship_rows = _inferred_warship_rows(ledger, shell_turn=3)
    assert len(warship_rows) == 1
    assert _known_built_turn(warship_rows[0]) == 2
    assert _ship_id_lte_bound(warship_rows[0]) == 33


def test_accelerated_first_reliable_arlowat_starting_mdsf_and_freighter_id_bounds():
    turn = load_turn_fixture("628580/1/turns/3.json")
    player_id = 2
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
    )

    ledger = ledger_for_player(snapshot, player_id)
    starting_rows = _homeworld_starting_freighter_rows(ledger, shell_turn=3)
    assert len(starting_rows) == 1
    assert starting_rows[0].fields.hull == FleetFieldKnown(16)
    assert starting_rows[0].fields.engine == FleetFieldKnown(9)
    assert starting_rows[0].build_option_sets == [
        FleetBuildOptionSet(
            hull_id=16,
            engine_id=9,
            beam_count=0,
            launcher_count=0,
        )
    ]
    assert _ship_id_lte_bound(starting_rows[0]) == 11

    inferred_freighters = [
        record
        for record in _inferred_freighter_rows(ledger, shell_turn=3)
        if record not in starting_rows
    ]
    assert len(inferred_freighters) == 2
    assert sorted(_known_built_turn(record) for record in inferred_freighters) == [1, 2]
    built_turn_one = next(r for r in inferred_freighters if _known_built_turn(r) == 1)
    built_turn_two = next(r for r in inferred_freighters if _known_built_turn(r) == 2)
    assert _ship_id_lte_bound(built_turn_one) == 22
    assert _ship_id_lte_bound(built_turn_two) == 33
    for record in inferred_freighters:
        assert record.build_option_sets == []


def test_post_accelerated_turn_uses_scoreboard_delta_placeholders_only():
    turn = load_turn_fixture("628580/1/turns/52.json")
    player_id = 8
    snapshot = ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
    )
    ledger = ledger_for_player(snapshot, player_id)
    warship_rows = _inferred_warship_rows(ledger, shell_turn=52)
    assert len(warship_rows) == 2
    for record in warship_rows:
        event = next(event for event in record.events if event.kind == "scoreboard_delta")
        assert "acceleratedIngest" not in event.payload
        assert _known_built_turn(record) == 52
