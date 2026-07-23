"""Regression: fleet@N must keep prior-turn ship identity when scores@N is no_exact.

Fingerprint (game 680224, Cyborg pl6, turn 5): turn-4 ledger had known/inferred
B200 identities (stable recordIds + buildOptionSets). Turn-5 scores closed as
``no_exact_solution``. Turn-5 fleet showed ``?`` hulls -- persisted ledger had
*new* recordIds and empty option sets (0 overlap with turn 4). Other players on
the same turn kept recordId continuity.

Contract: advancing from a final prior ledger must preserve existing record
identity across an unsolved scores turn. Empty / no_exact refine must not
rebuild the fleet from baseline.
"""

from __future__ import annotations

from dataclasses import replace

from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.chain import ensure_fleet_baseline
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    build_fleet_materialization_leg_job_wire,
)
from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.held_solutions import FleetInferenceSupport
from api.analytics.fleet.inferred_acquisition_ingest import ingest_turn_inferred_acquisitions
from api.analytics.fleet.serialization import (
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import (
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.scope import ComputeScope
from api.compute.wire import DependencyOutputs
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.fleet_fixtures import ledger_for_player
from tests.scores_exports_helpers import (
    inference_solution,
    perspective,
    schedule_row_with_ladder,
    ship_build_domain,
    ship_build_wire,
)

_FLEET_ANALYTIC_ID = "fleet"


def _turn_for_player(
    sample_turn,
    *,
    player_id: int,
    turn_number: int,
    shipchange: int,
    acceleratedturns: int = 3,
):
    return replace(
        sample_turn,
        ships=[],
        settings=replace(
            sample_turn.settings,
            turn=turn_number,
            acceleratedturns=acceleratedturns,
        ),
        game=replace(sample_turn.game, turn=turn_number),
        scores=[
            replace(
                score,
                turn=turn_number,
                ownerid=player_id,
                shipchange=shipchange,
                freighterchange=0,
            )
            for score in sample_turn.scores
            if score.ownerid == player_id
        ],
    )


def _inference_support(scheduler: InferenceRowScheduler) -> FleetInferenceSupport:
    return FleetInferenceSupport(
        scores_services=ScoresExportContext(
            persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            scheduler=scheduler,
        ),
    )


def _close_scores(
    inference: FleetInferenceSupport,
    turn,
    player_id: int,
    *,
    game_perspective: int,
    status: str,
    solutions: list[dict[str, object]] | None = None,
) -> None:
    persistence = inference.scores_services.persistence
    assert persistence is not None
    closed = list(solutions) if solutions is not None else []
    persistence.put_row(
        628580,
        game_perspective,
        turn.settings.turn,
        player_id,
        PersistedInferenceRow(
            status=status,
            summary="seed-closed",
            solution_count=len(closed),
            is_complete=True,
            solutions=closed,
        ),
    )


def _scope(turn_number: int, player_id: int, game_perspective: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=game_perspective,
        turn=turn_number,
        player_id=player_id,
    )


def _materialize_final_ledger(
    *,
    turn,
    player_id: int,
    game_perspective: int,
    fleet_services,
    inference: FleetInferenceSupport,
    prior: PersistedFleetLedger | None,
) -> PersistedFleetLedger:
    """Observation leg + finalization persist for one turn."""
    ctx = make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: inference.scores_services,
        },
    )
    dependency_outputs = DependencyOutputs()
    if prior is not None:
        prior_scope = _scope(turn.settings.turn - 1, player_id, game_perspective)
        dependency_outputs.put(
            prior_scope,
            {"persistedLedgerWire": persisted_fleet_ledger_to_json(prior)},
        )
    job_wire = build_fleet_materialization_leg_job_wire(
        _scope(turn.settings.turn, player_id, game_perspective),
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )
    observation = run_fleet_observation_leg(job_wire)
    assert observation.payload is not None
    result_wire = dict(observation.payload)
    result_wire["fleetPersistLeg"] = "finalization"
    notification = FleetPersistencePolicy().persist(
        ctx,
        _scope(turn.settings.turn, player_id, game_perspective),
        result_wire,
    )
    if notification is not None:
        notification()
    stored = fleet_services.persistence.get_ledger(
        628580, game_perspective, turn.settings.turn, player_id
    )
    assert stored is not None
    assert stored.provenance.is_final
    return stored


def test_no_exact_scores_turn_preserves_prior_record_ids_and_option_sets(sample_turn):
    """Final prior fleet@N-1 must survive fleet@N when scores@N is no_exact_solution.

    Cyborg/680224 turn-5 hang fingerprint: unsolved scores closed evidence, then
    fleet rematerialized without carrying turn-4 recordIds / buildOptionSets.
    """
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    game_perspective = perspective(sample_turn)
    turn_floor = _turn_for_player(sample_turn, player_id=player_id, turn_number=3, shipchange=1)
    turn_n = _turn_for_player(sample_turn, player_id=player_id, turn_number=4, shipchange=1)
    turn_n1 = _turn_for_player(sample_turn, player_id=player_id, turn_number=5, shipchange=1)

    schedule_row_with_ladder(
        scheduler,
        turn_floor,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=80,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-floor",
                        label="Floor Hull",
                        hull_id=13,
                        engine_id=9,
                    ),
                ),
            ),
        ],
    )
    schedule_row_with_ladder(
        scheduler,
        turn_n,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=90,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-b200",
                        label="B200 Class Probe",
                        hull_id=51,
                        engine_id=7,
                    ),
                ),
            ),
        ],
    )
    inference = _inference_support(scheduler)
    _close_scores(
        inference,
        turn_floor,
        player_id,
        game_perspective=game_perspective,
        status=STATUS_EXACT,
        solutions=[
            {
                "objectiveValue": 80,
                "actions": [],
                "shipBuilds": [
                    ship_build_wire(
                        combo_id="combo-floor",
                        label="Floor Hull",
                        hull_id=13,
                        engine_id=9,
                    ),
                ],
            }
        ],
    )
    _close_scores(
        inference,
        turn_n,
        player_id,
        game_perspective=game_perspective,
        status=STATUS_EXACT,
        solutions=[
            {
                "objectiveValue": 90,
                "actions": [],
                "shipBuilds": [
                    ship_build_wire(
                        combo_id="combo-b200",
                        label="B200 Class Probe",
                        hull_id=51,
                        engine_id=7,
                    ),
                ],
            }
        ],
    )
    _close_scores(
        inference,
        turn_n1,
        player_id,
        game_perspective=game_perspective,
        status=STATUS_NO_EXACT_SOLUTION,
        solutions=[],
    )

    fleet_services = build_ephemeral_fleet_compute_services(
        turn_n1,
        game_id=628580,
        perspective=game_perspective,
        stored_turns={3: turn_floor, 4: turn_n, 5: turn_n1},
        inference=inference,
    )

    floor = _materialize_final_ledger(
        turn=turn_floor,
        player_id=player_id,
        game_perspective=game_perspective,
        fleet_services=fleet_services,
        inference=inference,
        prior=None,
    )
    prior = _materialize_final_ledger(
        turn=turn_n,
        player_id=player_id,
        game_perspective=game_perspective,
        fleet_services=fleet_services,
        inference=inference,
        prior=floor,
    )
    prior_ids = {record.record_id for record in prior.ledger.records}
    prior_with_options = [
        record.record_id for record in prior.ledger.records if record.build_option_sets
    ]
    assert prior_ids
    assert prior_with_options, "turn N fixture must have inferred option sets"

    advanced = _materialize_final_ledger(
        turn=turn_n1,
        player_id=player_id,
        game_perspective=game_perspective,
        fleet_services=fleet_services,
        inference=inference,
        prior=prior,
    )

    advanced_ids = {record.record_id for record in advanced.ledger.records}
    assert prior_ids <= advanced_ids, (
        "fleet@N with scores no_exact_solution dropped prior recordIds "
        f"(lost={sorted(prior_ids - advanced_ids)}); 680224 Cyborg turn-5 fingerprint"
    )
    by_id = {record.record_id: record for record in advanced.ledger.records}
    for record_id in prior_with_options:
        assert by_id[record_id].build_option_sets, (
            f"prior record {record_id} lost buildOptionSets after no_exact turn"
        )


def test_stale_dependency_prior_must_not_override_final_disk_ledger(sample_turn):
    """DepOutputs prior wire must not beat a newer final ledger on disk.

    If job-wire build prefers a stale/empty DependencyOutputs ``persistedLedgerWire``
    over ``get_ledger(N-1)``, rematerialization rebuilds identity (new recordIds)
    even though disk still holds the refined prior -- matching the Cyborg t4/t5 split.
    """
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = sample_turn.scores[0].ownerid
    game_perspective = perspective(sample_turn)
    turn_floor = _turn_for_player(sample_turn, player_id=player_id, turn_number=3, shipchange=1)
    turn_n = _turn_for_player(sample_turn, player_id=player_id, turn_number=4, shipchange=1)
    turn_n1 = _turn_for_player(sample_turn, player_id=player_id, turn_number=5, shipchange=1)

    inference = _inference_support(scheduler)
    schedule_row_with_ladder(
        scheduler,
        turn_floor,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=40,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-floor",
                        label="Floor Hull",
                        hull_id=13,
                        engine_id=9,
                    ),
                ),
            ),
        ],
    )
    schedule_row_with_ladder(
        scheduler,
        turn_n,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=50,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-keep",
                        label="Keep Hull",
                        hull_id=13,
                        engine_id=9,
                    ),
                ),
            ),
        ],
    )
    _close_scores(
        inference,
        turn_floor,
        player_id,
        game_perspective=game_perspective,
        status=STATUS_EXACT,
        solutions=[
            {
                "objectiveValue": 40,
                "actions": [],
                "shipBuilds": [
                    ship_build_wire(
                        combo_id="combo-floor",
                        label="Floor Hull",
                        hull_id=13,
                        engine_id=9,
                    ),
                ],
            }
        ],
    )
    _close_scores(
        inference,
        turn_n,
        player_id,
        game_perspective=game_perspective,
        status=STATUS_EXACT,
        solutions=[
            {
                "objectiveValue": 50,
                "actions": [],
                "shipBuilds": [
                    ship_build_wire(
                        combo_id="combo-keep",
                        label="Keep Hull",
                        hull_id=13,
                        engine_id=9,
                    ),
                ],
            }
        ],
    )
    _close_scores(
        inference,
        turn_n1,
        player_id,
        game_perspective=game_perspective,
        status=STATUS_NO_EXACT_SOLUTION,
        solutions=[],
    )

    fleet_services = build_ephemeral_fleet_compute_services(
        turn_n1,
        game_id=628580,
        perspective=game_perspective,
        stored_turns={3: turn_floor, 4: turn_n, 5: turn_n1},
        inference=inference,
    )
    floor = _materialize_final_ledger(
        turn=turn_floor,
        player_id=player_id,
        game_perspective=game_perspective,
        fleet_services=fleet_services,
        inference=inference,
        prior=None,
    )
    disk_prior = _materialize_final_ledger(
        turn=turn_n,
        player_id=player_id,
        game_perspective=game_perspective,
        fleet_services=fleet_services,
        inference=inference,
        prior=floor,
    )
    disk_ids = {record.record_id for record in disk_prior.ledger.records}
    assert disk_ids

    # Stale observation-shaped prior: empty baseline ledger (no refined identities).
    stale_snapshot = ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(628580, game_perspective, turn_n),
        turn_n,
    )
    stale_prior = PersistedFleetLedger(
        ledger=ledger_for_player(stale_snapshot, player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=False,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    assert {record.record_id for record in stale_prior.ledger.records}.isdisjoint(disk_ids)

    ctx = make_analytic_query_context(
        turn_n1,
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: inference.scores_services,
        },
    )
    dependency_outputs = DependencyOutputs()
    dependency_outputs.put(
        _scope(4, player_id, game_perspective),
        {"persistedLedgerWire": persisted_fleet_ledger_to_json(stale_prior)},
    )
    job_wire = build_fleet_materialization_leg_job_wire(
        _scope(5, player_id, game_perspective),
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )
    wired_prior = persisted_fleet_ledger_from_json(job_wire["priorLedgerWire"])
    wired_ids = {record.record_id for record in wired_prior.ledger.records}
    assert wired_ids == disk_ids, (
        "job wire preferred stale DependencyOutputs prior over final disk ledger "
        f"(wired={sorted(wired_ids)} disk={sorted(disk_ids)}); "
        "680224 Cyborg turn-5 identity-loss fingerprint"
    )
