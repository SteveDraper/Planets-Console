"""Tests for scores compute orchestrator registration and tier_solve step."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_row_runner import TierJobOutcome
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.scores.compute_orchestration import (
    SCORES_TIER_SOLVE,
    ScoresPersistencePolicy,
    build_scores_tier_solve_job_wire,
    run_scores_tier_solve,
    tier_job_outcome_to_step_result,
)
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.tier_row_run_registry import (
    register_row_run,
    reset_tier_row_run_registry_for_tests,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import (
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    DependencyOutputs,
    build_compute_registry,
)
from api.services.inference_row_persistence_service import InferenceRowPersistenceService

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.fleet_chain_test_turns import HOST_TURN
from tests.fleet_exports_helpers import host_turn_at

_FLEET_ANALYTIC_ID = "fleet"


@pytest.fixture(autouse=True)
def _reset_scores_tier_registry():
    reset_tier_row_run_registry_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()


def _session_for_player(sample_turn, *, player_id: int | None = None) -> InferenceRowStreamSession:
    score = next(row for row in sample_turn.scores if player_id is None or row.ownerid == player_id)
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def _scores_scope(sample_turn, player_id: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )


def _register_run(sample_turn, *, player_id: int | None = None) -> RowRun:
    session = _session_for_player(sample_turn, player_id=player_id)
    run = RowRun(session)
    register_row_run(run)
    return run


def test_scores_registration_includes_tier_solve_step() -> None:
    step_kinds = tuple(step.step_kind for step in SCORES_REGISTRATION.compute_profile.steps)
    assert step_kinds == ("materialize", SCORES_TIER_SOLVE)
    assert build_compute_registry((SCORES_REGISTRATION,))[SCORES_ANALYTIC_ID]


def test_tier_job_outcome_mapping(sample_turn) -> None:
    run = _register_run(sample_turn)

    continue_result = tier_job_outcome_to_step_result(
        run, TierJobOutcome(enqueue_continuation=True)
    )
    assert continue_result.outcome == "continue"

    persist_result = tier_job_outcome_to_step_result(
        run,
        TierJobOutcome(
            row_complete=row_complete_with_summary(
                InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
                summary="exact",
            ),
        ),
    )
    assert persist_result.outcome == "persist"
    assert persist_result.payload["runId"] == run.run_id

    stopped_result = tier_job_outcome_to_step_result(
        run,
        TierJobOutcome(
            row_complete=row_complete_with_summary(
                InferenceResult(status=STATUS_STOPPED, solutions=(), diagnostics={}),
                summary="stopped",
            ),
        ),
    )
    assert stopped_result.outcome == "complete"


def test_build_scores_tier_solve_job_wire_requires_registered_row_run(sample_turn) -> None:
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={SCORES_ANALYTIC_ID: ScoresExportContext()},
    )
    player_id = sample_turn.scores[0].ownerid
    scope = _scores_scope(sample_turn, player_id)

    with pytest.raises(RuntimeError, match="registered RowRun"):
        build_scores_tier_solve_job_wire(
            scope,
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
        )

    run = _register_run(sample_turn, player_id=player_id)
    job_wire = build_scores_tier_solve_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert job_wire == {"runId": run.run_id}


def test_build_scores_tier_solve_job_wire_uses_fleet_dependency_output(sample_turn, persistence):
    host_turn = host_turn_at(sample_turn, HOST_TURN)[0]
    ctx = export_chain_query_context(host_turn, persistence=persistence)
    player_id = host_turn.scores[0].ownerid
    prior_persisted = PersistedFleetLedger(
        ledger=ensure_fleet_baseline_for_player(628580, 1, host_turn, player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    fleet_services = ctx.export_services["fleet"]
    prior_turn = HOST_TURN - 1
    fleet_services.persistence.put_ledger(
        628580,
        1,
        prior_turn,
        player_id,
        prior_persisted,
    )

    run = _register_run(host_turn, player_id=player_id)
    run.session.fleet_torp_input_status = "pending"

    prior_fleet_scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=prior_turn,
        player_id=player_id,
    )
    dependency_outputs = DependencyOutputs()
    dependency_outputs.put(
        prior_fleet_scope,
        {"persistedLedgerWire": persisted_fleet_ledger_to_json(prior_persisted)},
    )

    build_scores_tier_solve_job_wire(
        _scores_scope(host_turn, player_id),
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )

    assert run.session.fleet_torp_input_status == "applied"
    assert run.session.fleet_torp_overlay is not None


def test_scores_invalidation_generation_tracks_fleet_epoch(sample_turn, persistence):
    host_turn = host_turn_at(sample_turn, HOST_TURN)[0]
    ctx = export_chain_query_context(host_turn, persistence=persistence)
    player_id = host_turn.scores[0].ownerid
    fleet_services = ctx.export_services["fleet"]
    prior_persisted = PersistedFleetLedger(
        ledger=ensure_fleet_baseline_for_player(ctx.game_id, ctx.perspective, host_turn, player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    fleet_services.persistence.put_ledger(
        ctx.game_id,
        ctx.perspective,
        HOST_TURN - 1,
        player_id,
        prior_persisted,
    )
    policy = ScoresPersistencePolicy()
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=host_turn.settings.turn,
        player_id=player_id,
    )

    assert policy.invalidation_generation(ctx, scope) == 0
    fleet_services.persistence.invalidate_player_ledgers_from_turn(
        ctx.game_id,
        ctx.perspective,
        HOST_TURN - 1,
        player_id,
    )
    assert policy.invalidation_generation(ctx, scope) == 1


def test_scores_persistence_policy_persist_delegates_to_inference_service(
    sample_turn,
    memory_backend,
) -> None:
    run = _register_run(sample_turn)
    row_persistence = InferenceRowPersistenceService(memory_backend)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={SCORES_ANALYTIC_ID: ScoresExportContext(persistence=row_persistence)},
    )
    policy = ScoresPersistencePolicy()
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="persisted via orchestrator",
    )
    policy.persist(
        ctx,
        _scores_scope(sample_turn, run.session.player_id),
        {"runId": run.run_id, "rowComplete": row_complete},
    )

    stored = row_persistence.get_row(
        628580,
        1,
        sample_turn.settings.turn,
        run.session.player_id,
    )
    assert stored is not None
    assert stored.summary == "persisted via orchestrator"


def test_run_scores_tier_solve_returns_orchestrator_outcome(sample_turn) -> None:
    run = _register_run(sample_turn)
    outcome = TierJobOutcome(
        row_complete=row_complete_with_summary(
            InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            summary="terminal",
        ),
    )

    with patch(
        "api.analytics.scores.compute_orchestration.run_inference_tier_job",
        return_value=outcome,
    ):
        result = run_scores_tier_solve({"runId": run.run_id})

    assert result.outcome == "persist"


def test_orchestrator_runs_registered_tier_solve_step(sample_turn) -> None:
    from api.analytics.catalog import TurnAnalyticCatalogEntry
    from api.analytics.exports.catalog import AnalyticExportCatalog
    from api.analytics.exports.registry import EXPORT_REGISTRY
    from api.analytics.registration import TurnAnalyticRegistration
    from api.compute import AnalyticComputeProfile, ComputeStepSpec

    tier_catalog = AnalyticExportCatalog(
        analytic_id="scores-tier-probe",
        is_ensure_satisfied=lambda _ctx, _scope: False,
    )

    run = _register_run(sample_turn)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_registry={**EXPORT_REGISTRY, "scores-tier-probe": tier_catalog},
        export_services={SCORES_ANALYTIC_ID: ScoresExportContext()},
    )
    tier_registration = TurnAnalyticRegistration(
        catalog_entry=TurnAnalyticCatalogEntry(
            id="scores-tier-probe",
            name="scores-tier-probe",
            supports_table=True,
            supports_map=False,
            type="selectable",
        ),
        compute=lambda _ctx: {"analyticId": "scores-tier-probe"},
        export_catalog=tier_catalog,
        scope_key_spec=SCORES_REGISTRATION.scope_key_spec,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind=SCORES_TIER_SOLVE, backend="thread"),),
        ),
        persistence_policy=SCORES_REGISTRATION.persistence_policy,
        build_step_job_wires=((SCORES_TIER_SOLVE, build_scores_tier_solve_job_wire),),
        run_steps=((SCORES_TIER_SOLVE, run_scores_tier_solve),),
    )
    compute_registry = build_compute_registry((tier_registration,))
    submitted_scopes: list[ComputeScope] = []

    def pool_submitter(node, step, *, job_wire=None, run_step=None) -> None:
        del step, job_wire, run_step
        submitted_scopes.append(node.scope)

    orchestrator = ComputeOrchestrator(
        ctx,
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    scope = ComputeScope(
        analytic_id="scores-tier-probe",
        game_id=628580,
        perspective=1,
        turn=sample_turn.settings.turn,
        player_id=run.session.player_id,
    )
    terminal = TierJobOutcome(
        row_complete=row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="done",
        ),
    )

    with patch(
        "api.analytics.scores.compute_orchestration.run_inference_tier_job",
        return_value=terminal,
    ):
        handle = orchestrator.submit(ComputeRequest(scope=scope, step_kind=SCORES_TIER_SOLVE))
        assert submitted_scopes == [scope]
        result_wire = run_scores_tier_solve({"runId": run.run_id})
        orchestrator.complete_pool_step(scope, result_wire=result_wire)

    assert handle.state == "complete", handle.error
    assert handle.result_wire is not None
