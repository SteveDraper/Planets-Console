"""Tests for scores compute orchestrator registration and tier_solve step."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet import REGISTRATION as FLEET_REGISTRATION
from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_services import (
    build_ephemeral_fleet_compute_services,
    turn_chain_through,
)
from api.analytics.fleet.held_solutions import FleetInferenceSupport
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_row_runner import TierJobOutcome
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    _query_context_for_session,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
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
    _retire_row_run,
    get_row_run_for_scope,
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
    compute_scope_to_export_scope,
)
from api.compute.dag import plan_compute_dag
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


def test_retire_stale_run_preserves_replacement_scope_mapping(sample_turn) -> None:
    player_id = sample_turn.scores[0].ownerid
    old_run = _register_run(sample_turn, player_id=player_id)
    replacement_run = _register_run(sample_turn, player_id=player_id)
    scope = _scores_scope(sample_turn, player_id)

    _retire_row_run(old_run.run_id)

    assert get_row_run_for_scope(scope) is replacement_run


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
    # Stopped closes turn evidence when durable -- persist, do not soft-complete.
    assert stopped_result.outcome == "persist"

    empty_result = tier_job_outcome_to_step_result(run, TierJobOutcome())
    # Empty terminals must not DAG-complete (unlocks fleet with open evidence).
    assert empty_result.outcome == "waiting_deps"
    assert empty_result.wait_recovery is None


def test_run_scores_materialize_continues_to_tier_solve() -> None:
    """Materialize must continue into tier_solve so same-orchestrator fleet deps wait.

    Returning ``complete`` after materialize unblocked fleet@N before inference solutions
    existed (game 628580 t8): fleet refined empty, then scores tier_solve ran separately.
    """
    from api.analytics.scores.compute_orchestration import run_scores_materialize

    export_tree = {"analyticId": SCORES_ANALYTIC_ID}
    result = run_scores_materialize({"exportTree": export_tree})
    assert result.outcome == "continue"
    assert result.payload == export_tree


def test_scores_tier_solve_wire_ensure_schedules_row_run_when_missing(
    sample_turn,
) -> None:
    """Unsatisfied scope with no RowRun: tier wire re-ensures and schedules instead of skipping.

    False ``runId: None`` skips unlocked fleet with non-final provenance and left the
    scores multiplex in-progress (Fury/Colonies hang on game 628580 t8).
    """
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.compute_orchestration import (
        build_scores_tier_solve_job_wire,
        run_scores_materialize,
    )
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        get_row_run_for_scope,
        reset_tier_row_run_registry_for_tests,
    )
    from api.services.inference_row_persistence_service import InferenceRowPersistenceService
    from api.storage.memory_asset import MemoryAssetBackend

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0, defer_orchestrator_submit=True)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={
            SCORES_ANALYTIC_ID: ScoresExportContext(
                persistence=InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
                scheduler=scheduler,
            )
        },
    )
    player_id = sample_turn.scores[0].ownerid
    scope = _scores_scope(sample_turn, player_id)

    materialize = run_scores_materialize({"exportTree": {"ok": True}})
    assert materialize.outcome == "continue"

    job_wire = build_scores_tier_solve_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert job_wire.get("runId") is not None
    assert get_row_run_for_scope(scope) is not None


def test_build_scores_tier_solve_job_wire_skips_only_when_evidence_closed(
    sample_turn,
    persistence,
) -> None:
    """``runId: None`` skip requires closed turn evidence, not merely a missing RowRun."""
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.compute_orchestration import build_scores_tier_solve_job_wire
    from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    from tests.scores_exports_helpers import prior_turn_ensure_context, put_persisted_row

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0, defer_orchestrator_submit=True)
    ctx, export_scope, player_id, _, _ = prior_turn_ensure_context(
        sample_turn,
        persistence,
        scheduler=scheduler,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=export_scope.game_id,
        perspective=export_scope.perspective,
        turn=export_scope.turn,
        player_id=player_id,
    )

    # Open evidence + ensure still needs work (schedule patched away): hard fail --
    # not empty-complete, and not a soft defer without an armed wake publisher.
    with patch("api.analytics.scores.exports.schedule_inference_row"):
        with pytest.raises(RuntimeError, match="invariant broken"):
            build_scores_tier_solve_job_wire(
                scope,
                dependency_outputs=DependencyOutputs(),
                ctx=ctx,
            )

    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        host_turn=export_scope.turn,
    )
    skip_wire = build_scores_tier_solve_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert skip_wire["runId"] is None
    assert skip_wire["evidenceClosed"] is True


def test_build_scores_tier_solve_job_wire_attaches_registered_row_from_registry(
    sample_turn,
    persistence,
) -> None:
    """Live REGISTERED RowRun attaches from the single registry owner.

    Wire build must not depend on a scheduler-side RowRun dual cache.
    """
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.military_score_inference.inference_stream_rows import (
        schedule_inference_row,
    )
    from api.analytics.scores.export_snapshot import scores_inference_stream_scope
    from api.analytics.scores.tier_row_run_registry import (
        get_row_run_for_scope,
        reset_tier_row_run_registry_for_tests,
    )

    from tests.scores_exports_helpers import (
        GAME_ID,
        first_player_id,
        perspective,
        scores_query_context,
    )

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0, defer_orchestrator_submit=True)
    player_id = first_player_id(sample_turn)
    ctx = scores_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )
    export_scope = compute_scope_to_export_scope(scope)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
    )
    assert scheduled is not None
    run = scheduler.row_run_for_player(
        scores_inference_stream_scope(export_scope),
        player_id,
    )
    assert run is not None
    assert get_row_run_for_scope(scope) is run

    with (
        patch(
            "api.analytics.scores.exports.ensure_scores_export",
            return_value=True,
        ),
        patch.object(ScoresPersistencePolicy, "is_satisfied", return_value=False),
    ):
        wire = build_scores_tier_solve_job_wire(
            scope,
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
        )
    assert wire["runId"] == run.run_id
    assert wire["gameId"] == scope.game_id
    assert get_row_run_for_scope(scope) is run


def test_build_scores_tier_solve_job_wire_does_not_adopt_retired_row(
    sample_turn,
    persistence,
) -> None:
    """Retiring the registry shell drops adopt; no dual-cache recovery."""
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.military_score_inference.inference_stream_rows import (
        schedule_inference_row,
    )
    from api.analytics.scores.export_snapshot import scores_inference_stream_scope
    from api.analytics.scores.tier_row_run_registry import (
        _retire_row_run,
        get_row_run_for_scope,
        reset_tier_row_run_registry_for_tests,
    )

    from tests.scores_exports_helpers import (
        GAME_ID,
        first_player_id,
        perspective,
        scores_query_context,
    )

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0, defer_orchestrator_submit=True)
    player_id = first_player_id(sample_turn)
    ctx = scores_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )
    export_scope = compute_scope_to_export_scope(scope)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
    )
    assert scheduled is not None
    run = scheduler.row_run_for_player(
        scores_inference_stream_scope(export_scope),
        player_id,
    )
    assert run is not None
    _retire_row_run(run.run_id)
    assert get_row_run_for_scope(scope) is None
    assert (
        scheduler.row_run_for_player(
            scores_inference_stream_scope(export_scope),
            player_id,
        )
        is None
    )

    with (
        patch(
            "api.analytics.scores.exports.ensure_scores_export",
            return_value=True,
        ),
        patch.object(ScoresPersistencePolicy, "is_satisfied", return_value=False),
    ):
        with pytest.raises(RuntimeError, match="no attachable RowRun"):
            build_scores_tier_solve_job_wire(
                scope,
                dependency_outputs=DependencyOutputs(),
                ctx=ctx,
            )


def test_build_scores_tier_solve_job_wire_raises_when_ensure_satisfied_without_attachable_row(
    sample_turn,
    persistence,
) -> None:
    """Ensure-satisfied with open evidence and no RowRun is an invariant break."""
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests

    from tests.scores_exports_helpers import (
        GAME_ID,
        first_player_id,
        perspective,
        scores_query_context,
    )

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0, defer_orchestrator_submit=True)
    player_id = first_player_id(sample_turn)
    ctx = scores_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )

    with (
        patch(
            "api.analytics.scores.exports.ensure_scores_export",
            return_value=True,
        ),
        patch.object(ScoresPersistencePolicy, "is_satisfied", return_value=False),
    ):
        with pytest.raises(RuntimeError, match="invariant broken"):
            build_scores_tier_solve_job_wire(
                scope,
                dependency_outputs=DependencyOutputs(),
                ctx=ctx,
            )


def test_cheap_immediate_admission_closes_materialization_evidence_and_skip_completes(
    sample_turn,
    persistence,
) -> None:
    """ImmediateRowAdmission must not leave tier_solve in a forever-continue loop.

    Accelerated-window ``no_prior_turn`` is a permanent cheap terminal: ensure admits
    via ensure-ephemeral and never schedules a ``RowRun``. Materialization-aligned
    turn evidence (the probe fleet and ``ScoresPersistencePolicy.is_satisfied`` use)
    must see that terminal so wire-build emits the ``evidenceClosed`` skip and
    ``run_scores_tier_solve`` completes -- not ``{runId: None}`` + ``continue`` on
    every rebuild (busy hang that also blocks fleet finality after open-evidence
    persist refuse).
    """
    from dataclasses import replace

    from api.analytics.export_types import ExportScope
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.exports import (
        ensure_scores_export,
        is_scores_export_ensure_satisfied,
        is_scores_export_turn_evidence_closed,
    )
    from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests

    from tests.scores_exports_helpers import (
        GAME_ID,
        first_player_id,
        perspective,
        scores_query_context,
    )

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0, defer_orchestrator_submit=True)
    assert sample_turn.settings.acceleratedturns == 3

    turn_2 = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=2),
        game=replace(sample_turn.game, turn=2),
    )
    player_id = first_player_id(turn_2)
    ctx = scores_query_context(
        turn_2,
        persistence=persistence,
        scheduler=scheduler,
        stored_turns={2: turn_2},
    )
    export_scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(turn_2),
        turn=2,
        player_id=player_id,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=GAME_ID,
        perspective=perspective(turn_2),
        turn=2,
        player_id=player_id,
    )

    assert ensure_scores_export(ctx, export_scope) is True
    assert is_scores_export_ensure_satisfied(ctx, export_scope) is True
    assert get_row_run_for_scope(scope) is None

    # Materialization probe (fleet provenance / orchestrator satisfaction) must
    # agree with ensure that this cheap terminal closed turn evidence.
    assert is_scores_export_turn_evidence_closed(ctx, export_scope) is True
    assert ScoresPersistencePolicy().is_satisfied(ctx, scope) is True

    skip_wires = [
        build_scores_tier_solve_job_wire(
            scope,
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
        )
        for _ in range(3)
    ]
    assert all(
        wire.get("runId") is None and wire.get("evidenceClosed") is True for wire in skip_wires
    )
    assert all(run_scores_tier_solve(wire).outcome == "complete" for wire in skip_wires)


def test_historical_materialize_schedules_row_run_for_tier_solve(
    sample_turn,
    persistence,
) -> None:
    """Historical gap-fill: materialize schedules RowRun; no sync CP-SAT; tier has runId."""
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.compute_orchestration import (
        build_scores_materialize_job_wire,
        build_scores_tier_solve_job_wire,
    )
    from api.analytics.scores.tier_row_run_registry import get_row_run_for_scope

    from tests.scores_exports_helpers import prior_turn_ensure_context

    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    ctx, export_scope, player_id, _, _ = prior_turn_ensure_context(
        sample_turn,
        persistence,
        scheduler=scheduler,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=export_scope.game_id,
        perspective=export_scope.perspective,
        turn=export_scope.turn,
        player_id=player_id,
    )

    with patch("api.analytics.scores.inference.get_scores_row_inference") as mock_inference:
        materialize_wire = build_scores_materialize_job_wire(
            scope,
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
        )
        mock_inference.assert_not_called()

    assert "exportTree" in materialize_wire
    assert get_row_run_for_scope(scope) is not None

    tier_wire = build_scores_tier_solve_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert tier_wire.get("runId") is not None


def test_historical_materialize_skips_tier_when_already_persisted(
    sample_turn,
    persistence,
) -> None:
    """Persisted historical scope: materialize short-circuits; tier_solve gets skip sentinel."""
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.compute_orchestration import (
        build_scores_materialize_job_wire,
        build_scores_tier_solve_job_wire,
    )
    from api.serialization.inference_row_persistence import PersistedInferenceRow

    from tests.scores_exports_helpers import prior_turn_ensure_context, put_persisted_row

    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    ctx, export_scope, player_id, _, _ = prior_turn_ensure_context(
        sample_turn,
        persistence,
        scheduler=scheduler,
    )
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        host_turn=export_scope.turn,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=export_scope.game_id,
        perspective=export_scope.perspective,
        turn=export_scope.turn,
        player_id=player_id,
    )

    with patch("api.analytics.scores.exports.schedule_inference_row") as mock_schedule:
        build_scores_materialize_job_wire(
            scope,
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
        )
        mock_schedule.assert_not_called()

    tier_wire = build_scores_tier_solve_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert tier_wire["runId"] is None
    assert tier_wire["evidenceClosed"] is True


def test_historical_schedule_tier_solve_persists_via_scores_persistence_policy(
    sample_turn,
    persistence,
) -> None:
    """Historical gap-fill: schedule without sync ensure; tier_solve persists via policy."""
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.compute_orchestration import (
        build_scores_materialize_job_wire,
        build_scores_tier_solve_job_wire,
    )

    from tests.scores_exports_helpers import GAME_ID, perspective, prior_turn_ensure_context

    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    ctx, export_scope, player_id, _, _ = prior_turn_ensure_context(
        sample_turn,
        persistence,
        scheduler=scheduler,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=export_scope.game_id,
        perspective=export_scope.perspective,
        turn=export_scope.turn,
        player_id=player_id,
    )
    host_turn = export_scope.turn
    assert persistence.get_row(GAME_ID, perspective(sample_turn), host_turn, player_id) is None

    with (
        patch("api.analytics.scores.inference.get_scores_row_inference") as mock_inference,
        patch.object(persistence, "put_row") as mock_put_row,
    ):
        build_scores_materialize_job_wire(
            scope,
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
        )
        mock_inference.assert_not_called()
        mock_put_row.assert_not_called()

    assert get_row_run_for_scope(scope) is not None
    assert persistence.get_row(GAME_ID, perspective(sample_turn), host_turn, player_id) is None

    tier_wire = build_scores_tier_solve_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert tier_wire.get("runId") is not None

    outcome = TierJobOutcome(
        row_complete=row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="historical persist via orchestrator",
        ),
    )
    with patch(
        "api.analytics.scores.compute_orchestration.run_inference_tier_job",
        return_value=outcome,
    ):
        result = run_scores_tier_solve(tier_wire)

    assert result.outcome == "persist"
    ScoresPersistencePolicy().persist(ctx, scope, result.payload)

    stored = persistence.get_row(GAME_ID, perspective(sample_turn), host_turn, player_id)
    assert stored is not None
    assert stored.summary == "historical persist via orchestrator"


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


def test_scores_tier_wire_stale_dependency_prior_must_not_override_final_disk(
    sample_turn, persistence
):
    """Non-final DepOutputs fleet prior must not beat a final disk ledger.

    Mirrors fleet ``test_stale_dependency_prior_must_not_override_final_disk_ledger``:
    scores tier-wire prior selection must share ``select_fleet_prior_persisted`` so
    inference overlay / max-tech gates see the refined disk ledger.
    """
    host_turn = host_turn_at(sample_turn, HOST_TURN)[0]
    ctx = export_chain_query_context(host_turn, persistence=persistence)
    player_id = host_turn.scores[0].ownerid
    prior_turn = HOST_TURN - 1

    disk_final = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(
            player_id=player_id,
            records=[
                FleetShipRecord(
                    record_id="disk-final",
                    fields=FleetShipRecordFields(launchers=FleetFieldKnown(6)),
                ),
            ],
        ),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    stale_prior = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(
            player_id=player_id,
            records=[
                FleetShipRecord(
                    record_id="stale-deps",
                    fields=FleetShipRecordFields(launchers=FleetFieldKnown(3)),
                ),
            ],
        ),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=False,
            prior_ledger_at_n_minus_1=True,
        ),
    )

    fleet_services = ctx.export_services["fleet"]
    fleet_services.persistence.put_ledger(
        628580,
        1,
        prior_turn,
        player_id,
        disk_final,
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
        {"persistedLedgerWire": persisted_fleet_ledger_to_json(stale_prior)},
    )

    build_scores_tier_solve_job_wire(
        _scores_scope(host_turn, player_id),
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )

    assert run.session.fleet_torp_input_status == "applied"
    assert run.session.fleet_torp_overlay is not None
    belief = run.session.fleet_torp_overlay.belief_set.torp_ids
    assert 6 in belief, "tier wire preferred stale DepOutputs prior over final disk"
    assert 3 not in belief


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

    # Same-player activity on an unrelated turn (or player-scoped only) must not
    # advance scores@N's prior-fleet epoch.
    gen_after_prior = policy.invalidation_generation(ctx, scope)
    fleet_services.persistence.bump_player_and_turn_invalidations(
        ctx.game_id,
        ctx.perspective,
        player_id,
        turns=(HOST_TURN + 5,),
    )
    assert policy.invalidation_generation(ctx, scope) == gen_after_prior


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
        handle = orchestrator.submit(
            ComputeRequest(ctx=ctx, scope=scope, step_kind=SCORES_TIER_SOLVE),
        )
        assert submitted_scopes == [scope]
        result_wire = run_scores_tier_solve({"runId": run.run_id})
        orchestrator.complete_pool_step(scope, result_wire=result_wire)

    assert handle.state == "complete", handle.error
    assert handle.result_wire is not None


def test_orchestrator_waits_empty_soft_terminal_without_redispatch(sample_turn) -> None:
    """Empty tier soft-defers to waiting_deps; force_fresh wake re-queues work.

    Soft defer must not graft the scores scope onto its own dependency_scopes --
    that self-edge leaves ``_deps_complete`` false forever so force_fresh attach
    cannot promote the node out of waiting_deps.
    """
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
    defer_notifications: list[str] = []

    def record_outcome(snapshot) -> None:
        if snapshot.scope.analytic_id == "scores-tier-probe":
            defer_notifications.append(snapshot.state)

    unregister = orchestrator.observers.register_scope_outcome_listener(
        record_outcome,
    )

    with patch(
        "api.analytics.scores.compute_orchestration.run_inference_tier_job",
        return_value=TierJobOutcome(),
    ):
        handle = orchestrator.submit(
            ComputeRequest(ctx=ctx, scope=scope, step_kind=SCORES_TIER_SOLVE),
        )
        assert submitted_scopes == [scope]
        result_wire = run_scores_tier_solve(
            {
                "runId": run.run_id,
                "gameId": scope.game_id,
                "perspective": scope.perspective,
                "turn": scope.turn,
                "playerId": scope.player_id,
            }
        )
        assert result_wire.outcome == "waiting_deps"
        assert result_wire.wait_recovery is None
        orchestrator.complete_pool_step(scope, result_wire=result_wire)

    unregister()
    node = orchestrator.nodes[scope]
    assert node.state == "waiting_deps"
    assert handle.state == "waiting_deps"
    assert scope not in node.dependency_scopes
    assert defer_notifications == []
    assert submitted_scopes == [scope]
    assert orchestrator.metrics.epoch_discards == 1
    # Soft park must not satisfy dependents the way complete would.
    from api.compute.orchestrator import ComputeNodeRun

    dependent = ComputeNodeRun(
        scope=ComputeScope(
            analytic_id="fleet-probe",
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn=scope.turn,
            player_id=scope.player_id,
        ),
        dependency_scopes=(scope,),
        state="waiting_deps",
    )
    assert orchestrator._deps_complete(dependent) is False

    submits_before_wake = len(submitted_scopes)
    with patch(
        "api.analytics.scores.compute_orchestration.run_inference_tier_job",
        return_value=TierJobOutcome(
            row_complete=row_complete_with_summary(
                InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
                summary="done",
            ),
        ),
    ):
        orchestrator.submit(
            ComputeRequest(
                ctx=ctx,
                scope=scope,
                step_kind=SCORES_TIER_SOLVE,
                force_fresh=True,
            ),
        )

    assert len(submitted_scopes) > submits_before_wake
    assert node.state in {"ready", "running"}
    assert scope not in node.dependency_scopes


def test_orchestrator_entry_tier_solve_dispatches_with_registered_scheduler_row(
    sample_turn,
    persistence,
) -> None:
    player_id = sample_turn.scores[0].ownerid
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(
        InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=sample_turn.settings.turn,
        )
    )
    session = _session_for_player(sample_turn, player_id=player_id)
    scheduler.enqueue_tier_ladder(session, stream_token=stream_token)

    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
        seed_fleet_prerequisites_for=player_id,
    )
    compute_registry = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))
    submitted_scopes: list[ComputeScope] = []

    def pool_submitter(node, step, *, job_wire=None, run_step=None) -> None:
        del step, job_wire, run_step
        submitted_scopes.append(node.scope)

    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    scope = _scores_scope(sample_turn, player_id)

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope, step_kind=SCORES_TIER_SOLVE))

    assert handle.state == "running"
    assert submitted_scopes == [scope]
    assert orchestrator.nodes[scope].profile_step_index == 1


def test_stream_query_context_plans_prior_turn_fleet_dependency(
    sample_turn,
    persistence,
) -> None:
    host_turn = host_turn_at(sample_turn, HOST_TURN)[0]
    turns = turn_chain_through(host_turn)
    player_id = host_turn.scores[0].ownerid
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)

    def load_turn(turn_number: int):
        return turns.get(turn_number)

    scores_services = ScoresExportContext(
        persistence=persistence,
        scheduler=scheduler,
    )
    fleet_services = build_ephemeral_fleet_compute_services(
        host_turn,
        game_id=628580,
        perspective=1,
        stored_turns=turns,
        inference=FleetInferenceSupport(scores_services=scores_services),
    )
    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(
            host_turn.scores[0],
            host_turn,
            load_scoreboard_turn=load_turn,
        ),
        turn=host_turn,
        game_id=628580,
        perspective=1,
        turn_number=host_turn.settings.turn,
        load_scoreboard_turn=load_turn,
        export_services={
            SCORES_ANALYTIC_ID: scores_services,
            _FLEET_ANALYTIC_ID: fleet_services,
        },
    )
    ctx = _query_context_for_session(session, scheduler=scheduler)
    scope = _scores_scope(host_turn, player_id)
    prior_fleet_scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=HOST_TURN - 1,
        player_id=player_id,
    )

    planned = plan_compute_dag(
        ctx,
        SCORES_ANALYTIC_ID,
        compute_scope_to_export_scope(scope),
        compute_registry=build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION)),
        force_root=True,
    )
    planned_by_scope = {node.scope: node for node in planned}

    assert prior_fleet_scope in planned_by_scope
    assert scope in planned_by_scope
    assert prior_fleet_scope in planned_by_scope[scope].dependency_scopes


def test_row_run_adopt_refreshes_waiting_scores_node(sample_turn, persistence) -> None:
    """Background RowRun register must force_fresh-refresh a waiting_deps scores node."""
    from api.analytics.military_score_inference.inference_scheduler import (
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.compute_orchestration import wake_scores_scope
    from api.analytics.scores_defer_wake import ScoresWakeReason
    from api.compute import runtime as compute_runtime
    from api.compute.orchestrator import ComputeNodeRun
    from api.compute.runtime import reset_orchestrators_for_tests

    reset_orchestrators_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()

    player_id = sample_turn.scores[0].ownerid
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=False)
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
        seed_fleet_prerequisites_for=player_id,
    )
    scope = _scores_scope(sample_turn, player_id)
    compute_registry = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))
    submitted_scopes: list[ComputeScope] = []

    def pool_submitter(node, step, *, job_wire=None, run_step=None) -> None:
        del step, job_wire, run_step
        submitted_scopes.append(node.scope)

    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    compute_runtime._process_orchestrator = orchestrator

    waiting = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="waiting_deps",
        priority_band="background",
        profile_step_index=1,
        step_index=1,
        bundle=ComputeRequest(ctx=ctx, scope=scope).resolved_bundle(),
    )
    orchestrator._nodes[scope] = waiting

    assert (
        wake_scores_scope(
            scope,
            ctx=ctx,
            reason=ScoresWakeReason.ROW_RUN_ADOPTED,
        )
        is True
    )
    assert waiting.state in {"ready", "running"}
    assert submitted_scopes == [scope]

    submitted_scopes.clear()
    assert (
        wake_scores_scope(
            scope,
            ctx=ctx,
            reason=ScoresWakeReason.ROW_RUN_ADOPTED,
        )
        is False
    )
    assert submitted_scopes == []


def test_enqueue_without_stream_token_wakes_parked_scores_node(
    sample_turn,
    persistence,
) -> None:
    """enqueue_tier_ladder with no stream token still wakes a parked scores DAG."""
    from api.analytics.military_score_inference.inference_scheduler import (
        reset_inference_row_scheduler_for_tests,
    )
    from api.compute import runtime as compute_runtime
    from api.compute.orchestrator import ComputeNodeRun
    from api.compute.runtime import reset_orchestrators_for_tests

    reset_orchestrators_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()

    player_id = sample_turn.scores[0].ownerid
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=False)
    session = _session_for_player(sample_turn, player_id=player_id)
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
        seed_fleet_prerequisites_for=player_id,
    )
    scope = _scores_scope(sample_turn, player_id)
    compute_registry = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))
    submitted_scopes: list[ComputeScope] = []

    def pool_submitter(node, step, *, job_wire=None, run_step=None) -> None:
        del step, job_wire, run_step
        submitted_scopes.append(node.scope)

    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    compute_runtime._process_orchestrator = orchestrator
    parked = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="parked",
        priority_band="background",
        profile_step_index=1,
        step_index=1,
        bundle=ComputeRequest(ctx=ctx, scope=scope).resolved_bundle(),
    )
    orchestrator._nodes[scope] = parked

    # No active stream token: background ensure path registers RowRun and must wake.
    scheduler.enqueue_tier_ladder(session, stream_token=None)

    assert parked.state in {"ready", "running"}
    assert submitted_scopes == [scope]
    assert get_row_run_for_scope(scope) is not None
