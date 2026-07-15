"""Fleet persist must publish post-refine ledger on result_wire (#220).

Phase-1 interpreter legs omit scores option sets; phase-2 persist refines them.
Stream listeners and next-leg DependencyOutputs priors must see the refined wire,
not the phase-1 interpreter payload left on the node after the interpreter step.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.chain import ensure_fleet_baseline
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    build_fleet_materialization_leg_job_wire,
)
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
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.scope import ComputeScope
from api.compute.wire import DependencyOutputs
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


def _turn_with_warship_delta(sample_turn, *, shipchange: int, turn_number: int | None = None):
    player_id = sample_turn.scores[0].ownerid
    resolved_turn = sample_turn.settings.turn if turn_number is None else turn_number
    turn = replace(
        sample_turn,
        ships=[],
        settings=replace(sample_turn.settings, turn=resolved_turn),
        game=replace(sample_turn.game, turn=resolved_turn),
        scores=[
            replace(
                score,
                turn=resolved_turn,
                ownerid=player_id,
                shipchange=shipchange,
                freighterchange=0,
            )
            for score in sample_turn.scores
            if score.ownerid == player_id
        ],
    )
    return turn, player_id


def _phase1_persisted_with_placeholders(turn, *, player_id: int, game_perspective: int):
    snapshot = ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(628580, game_perspective, turn),
        turn,
    )
    ledger = ledger_for_player(snapshot, player_id)
    assert ledger.records
    assert all(record.build_option_sets == [] for record in ledger.records)
    return PersistedFleetLedger(
        ledger=ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )


def _inference_support(scheduler: InferenceRowScheduler) -> FleetInferenceSupport:
    return FleetInferenceSupport(
        scores_services=ScoresExportContext(
            persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            scheduler=scheduler,
        ),
    )


def _close_scores_turn_evidence(
    inference: FleetInferenceSupport,
    turn,
    player_id: int,
    *,
    game_perspective: int,
    solutions: list[dict[str, object]] | None = None,
) -> None:
    """Persist exact scores@N so fleet persist may close turnEvidenceAtN.

    Solutions must be the wire payloads refine will read -- an empty exact row
    closes evidence but starves option-set assignment.
    """
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    persistence = inference.scores_services.persistence
    assert persistence is not None
    closed_solutions = list(solutions) if solutions is not None else []
    persistence.put_row(
        628580,
        game_perspective,
        turn.settings.turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seed-closed",
            solution_count=len(closed_solutions),
            is_complete=True,
            solutions=closed_solutions,
        ),
    )


def test_persist_writes_refined_option_sets_onto_result_wire(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    turn, player_id = _turn_with_warship_delta(sample_turn, shipchange=2)
    game_perspective = perspective(turn)
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
    inference = _inference_support(scheduler)
    _close_scores_turn_evidence(
        inference,
        turn,
        player_id,
        game_perspective=game_perspective,
        solutions=[
            {
                "objectiveValue": 90,
                "actions": [],
                "shipBuilds": [
                    ship_build_wire(
                        combo_id="combo-a",
                        label="Cruiser A",
                        hull_id=13,
                        engine_id=9,
                    ),
                    ship_build_wire(
                        combo_id="combo-a",
                        label="Cruiser A",
                        hull_id=13,
                        engine_id=9,
                        count=1,
                    ),
                ],
            }
        ],
    )
    fleet_services = build_ephemeral_fleet_compute_services(
        turn,
        game_id=628580,
        perspective=game_perspective,
        stored_turns={turn.settings.turn: turn},
        inference=inference,
    )
    ctx = make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: ScoresExportContext(),
        },
    )
    phase1 = _phase1_persisted_with_placeholders(
        turn, player_id=player_id, game_perspective=game_perspective
    )

    result_wire = {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(phase1),
        "materializeTurn": turn.settings.turn,
    }
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=game_perspective,
        turn=turn.settings.turn,
        player_id=player_id,
    )

    notification = FleetPersistencePolicy().persist(ctx, scope, result_wire)
    if notification is not None:
        notification()

    refined = persisted_fleet_ledger_from_json(result_wire["persistedLedgerWire"])
    assert all(len(record.build_option_sets) > 0 for record in refined.ledger.records)
    assert refined.ledger.records[0].build_option_sets[0].combo_id == "combo-a"
    assert refined.ledger.records[0].build_option_sets[0].hull_id == 13

    stored = fleet_services.persistence.get_ledger(
        628580, game_perspective, turn.settings.turn, player_id
    )
    assert stored is not None
    assert persisted_fleet_ledger_to_json(stored) == result_wire["persistedLedgerWire"]


def test_next_leg_prior_from_dependency_outputs_keeps_refined_option_sets(sample_turn):
    """Same-run chaining: prior DependencyOutputs wire must carry option sets (#220)."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    turn_n, player_id = _turn_with_warship_delta(sample_turn, shipchange=1, turn_number=5)
    turn_n1, _ = _turn_with_warship_delta(sample_turn, shipchange=0, turn_number=6)
    game_perspective = perspective(turn_n)
    schedule_row_with_ladder(
        scheduler,
        turn_n,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=90,
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-prior",
                        label="Prior Hull",
                        hull_id=13,
                        engine_id=9,
                    ),
                ),
            ),
        ],
    )
    schedule_row_with_ladder(
        scheduler,
        turn_n1,
        player_id,
        merged_solutions=[],
    )
    inference = _inference_support(scheduler)
    _close_scores_turn_evidence(
        inference,
        turn_n,
        player_id,
        game_perspective=game_perspective,
        solutions=[
            {
                "objectiveValue": 90,
                "actions": [],
                "shipBuilds": [
                    ship_build_wire(
                        combo_id="combo-prior",
                        label="Prior Hull",
                        hull_id=13,
                        engine_id=9,
                    ),
                ],
            }
        ],
    )
    _close_scores_turn_evidence(inference, turn_n1, player_id, game_perspective=game_perspective)
    fleet_services = build_ephemeral_fleet_compute_services(
        turn_n1,
        game_id=628580,
        perspective=game_perspective,
        stored_turns={5: turn_n, 6: turn_n1},
        inference=inference,
    )
    ctx = make_analytic_query_context(
        turn_n1,
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: ScoresExportContext(),
        },
    )

    phase1_n = _phase1_persisted_with_placeholders(
        turn_n, player_id=player_id, game_perspective=game_perspective
    )
    result_wire_n = {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(phase1_n),
        "materializeTurn": 5,
    }
    scope_n = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=game_perspective,
        turn=5,
        player_id=player_id,
    )
    notification = FleetPersistencePolicy().persist(ctx, scope_n, result_wire_n)
    if notification is not None:
        notification()

    dependency_outputs = DependencyOutputs()
    dependency_outputs.put(scope_n, result_wire_n)

    job_wire = build_fleet_materialization_leg_job_wire(
        ComputeScope(
            analytic_id=_FLEET_ANALYTIC_ID,
            game_id=628580,
            perspective=game_perspective,
            turn=6,
            player_id=player_id,
        ),
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )
    prior = persisted_fleet_ledger_from_json(job_wire["priorLedgerWire"])
    assert any(
        any(option.combo_id == "combo-prior" for option in record.build_option_sets)
        for record in prior.ledger.records
    )


def test_empty_prior_dependency_wire_falls_back_to_persistence(sample_turn):
    """Satisfaction short-circuit leaves ``{}``; next leg must not KeyError (#222)."""
    reset_inference_row_scheduler_for_tests()
    turn_n, player_id = _turn_with_warship_delta(sample_turn, shipchange=1, turn_number=5)
    turn_n1, _ = _turn_with_warship_delta(sample_turn, shipchange=0, turn_number=6)
    game_perspective = perspective(turn_n)
    fleet_services = build_ephemeral_fleet_compute_services(
        turn_n1,
        game_id=628580,
        perspective=game_perspective,
        stored_turns={5: turn_n, 6: turn_n1},
        inference=_inference_support(InferenceRowScheduler(worker_count=0)),
    )
    ctx = make_analytic_query_context(
        turn_n1,
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: ScoresExportContext(),
        },
    )
    snapshot = ensure_fleet_baseline(628580, game_perspective, turn_n)
    prior_persisted = PersistedFleetLedger(
        ledger=ledger_for_player(snapshot, player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    fleet_services.persistence.put_ledger(
        628580,
        game_perspective,
        5,
        player_id,
        prior_persisted,
    )
    prior_scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=game_perspective,
        turn=5,
        player_id=player_id,
    )
    dependency_outputs = DependencyOutputs()
    dependency_outputs.put(prior_scope, {})

    job_wire = build_fleet_materialization_leg_job_wire(
        ComputeScope(
            analytic_id=_FLEET_ANALYTIC_ID,
            game_id=628580,
            perspective=game_perspective,
            turn=6,
            player_id=player_id,
        ),
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )
    assert job_wire["priorLedgerWire"] is not None
    stored = fleet_services.persistence.get_ledger(628580, game_perspective, 5, player_id)
    assert stored is not None
    assert FleetPersistencePolicy().satisfied_result_wire(ctx, prior_scope) == {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(stored)
    }


def test_persist_refuses_when_scores_turn_evidence_open(sample_turn):
    """Open scores evidence must raise PersistDeferredError, not quiet non-final complete."""
    from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery
    from api.errors import FleetScoresEvidenceOpenError

    reset_inference_row_scheduler_for_tests()
    turn, player_id = _turn_with_warship_delta(sample_turn, shipchange=2, turn_number=8)
    game_perspective = perspective(turn)
    fleet_services = build_ephemeral_fleet_compute_services(
        turn,
        game_id=628580,
        perspective=game_perspective,
        stored_turns={turn.settings.turn: turn},
        inference=_inference_support(InferenceRowScheduler(worker_count=0)),
    )
    ctx = make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: ScoresExportContext(),
        },
    )
    phase1 = _phase1_persisted_with_placeholders(
        turn, player_id=player_id, game_perspective=game_perspective
    )
    result_wire = {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(phase1),
        "materializeTurn": turn.settings.turn,
    }
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=game_perspective,
        turn=turn.settings.turn,
        player_id=player_id,
    )

    with pytest.raises(FleetScoresEvidenceOpenError) as raised:
        FleetPersistencePolicy().persist(ctx, scope, result_wire)

    assert isinstance(raised.value, PersistDeferredError)
    assert raised.value.recovery == PersistDependencyRecovery(
        dependency_scope=ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=628580,
            perspective=game_perspective,
            turn=turn.settings.turn,
            player_id=player_id,
        ),
        force_fresh=True,
        step_kind="tier_solve",
    )
    assert (
        fleet_services.persistence.get_ledger(
            628580, game_perspective, turn.settings.turn, player_id
        )
        is None
    )
