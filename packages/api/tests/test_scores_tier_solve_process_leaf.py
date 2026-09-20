"""Process-plane scores ``tier_solve``: thread identity wire, SAT-session Solve seam."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.military_score_inference.tier_policy import (
    ComponentFilter,
    InferenceCatalogFilters,
    InferenceTierPolicyStep,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.compute_orchestration import (
    ScoresPersistencePolicy,
    apply_scores_tier_solve_step_result,
    build_scores_tier_solve_job_wire,
    map_scores_tier_solve_remote_result,
)
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.tier_row_run_registry import (
    get_row_run_for_scope,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
)
from api.analytics.scores.tier_solve_backend import (
    SCORES_TIER_SOLVE_BACKEND_ENV,
    resolve_scores_tier_solve_backend,
)
from api.analytics.scores.tier_solve_wire import (
    WIRE_EVIDENCE_CLOSED,
    WIRE_GAME_ID,
    WIRE_LADDER_STATE,
    WIRE_ORCHESTRATION_SKIP,
    WIRE_PERSPECTIVE,
    WIRE_PLAYER_ID,
    WIRE_RUN_ID,
    WIRE_TURN,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeScope, DependencyOutputs
from api.compute.sat_session import SatSearchCollectionResult, run_sat_search_session
from api.compute.wire import StepResult, coerce_step_result, orchestration_plane_skip_result
from api.services.inference_row_persistence_service import InferenceRowPersistenceService

from tests.scores_exports_helpers import inference_target_player_id, minimal_stream_query_context

_THREAD_IDENTITY_KEYS = frozenset(
    {
        WIRE_RUN_ID,
        WIRE_GAME_ID,
        WIRE_PERSPECTIVE,
        WIRE_TURN,
        WIRE_PLAYER_ID,
    }
)
_PROCESS_UNWIRED = "SAT-session"


@pytest.fixture(autouse=True)
def _reset_scores_tier_registry():
    reset_tier_row_run_registry_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()


def _tiny_policy_step(
    step_id: str = "tiny",
    *,
    max_seconds: float | None = None,
) -> InferenceTierPolicyStep:
    return InferenceTierPolicyStep(
        id=step_id,
        filters=InferenceCatalogFilters(
            hulls=ComponentFilter(tech_levels=(1,)),
            engines=ComponentFilter(tech_levels=(1,)),
            beams=ComponentFilter(tech_levels=(1,)),
            launchers=ComponentFilter(tech_levels=(1,)),
        ),
        beam_slot_counts="none",
        launcher_slot_counts="none",
        aggregate_allowlist={},
        alpha=0,
        max_seeds=0,
        max_seconds=max_seconds,
    )


def _scores_scope(sample_turn, player_id: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )


def _register_run(
    sample_turn,
    *,
    player_id: int,
    ladder: PolicyLadderState | None = None,
) -> RowRun:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    from api.analytics.military_score_inference.inference_stream_session import (
        InferenceRowStreamSession,
    )

    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=sample_turn.settings.turn,
        query_context=minimal_stream_query_context(sample_turn),
    )
    run = RowRun(session)
    if ladder is not None:
        run.ladder_state = ladder
    register_row_run(run)
    return run


def _opt_in_process_backend(monkeypatch) -> None:
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")


def _open_evidence_ctx(sample_turn):
    scheduler = InferenceRowScheduler(worker_count=0, defer_orchestrator_submit=True)
    return make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={
            SCORES_ANALYTIC_ID: ScoresExportContext(scheduler=scheduler),
        },
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )


def test_resolve_scores_tier_solve_backend_defaults_to_thread(monkeypatch):
    monkeypatch.delenv(SCORES_TIER_SOLVE_BACKEND_ENV, raising=False)
    assert resolve_scores_tier_solve_backend() == "thread"


def test_resolve_scores_tier_solve_backend_env_process(monkeypatch):
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    assert resolve_scores_tier_solve_backend() == "process"


def test_resolve_scores_tier_solve_backend_frozen_honors_process_env(monkeypatch):
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    monkeypatch.setattr("api.compute.backend_runtime.process_is_frozen", lambda: True)
    assert resolve_scores_tier_solve_backend() == "process"


def test_resolve_scores_step_backend_does_not_remap_tier_solve(monkeypatch):
    from api.analytics.scores.compute_orchestration import (
        SCORES_MATERIALIZE,
        SCORES_TIER_SOLVE,
        resolve_scores_step_backend,
    )

    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    assert resolve_scores_step_backend(SCORES_TIER_SOLVE, "thread") == "thread"
    assert resolve_scores_step_backend(SCORES_MATERIALIZE, "inline") == "inline"


def test_open_evidence_thread_wire_is_identity(
    sample_turn,
    monkeypatch,
) -> None:
    monkeypatch.delenv(SCORES_TIER_SOLVE_BACKEND_ENV, raising=False)
    player_id = inference_target_player_id(sample_turn)
    run = _register_run(sample_turn, player_id=player_id)
    ctx = _open_evidence_ctx(sample_turn)
    wire = build_scores_tier_solve_job_wire(
        _scores_scope(sample_turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert set(wire) == _THREAD_IDENTITY_KEYS
    assert wire[WIRE_RUN_ID] == run.run_id


def test_open_evidence_process_wire_is_identity(
    sample_turn,
    monkeypatch,
) -> None:
    _opt_in_process_backend(monkeypatch)
    player_id = inference_target_player_id(sample_turn)
    run = _register_run(sample_turn, player_id=player_id)
    ctx = _open_evidence_ctx(sample_turn)
    wire = build_scores_tier_solve_job_wire(
        _scores_scope(sample_turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert set(wire) == _THREAD_IDENTITY_KEYS
    assert wire[WIRE_RUN_ID] == run.run_id
    assert "storageRoot" not in wire


def test_open_evidence_frozen_process_env_wire_is_identity(
    sample_turn,
    monkeypatch,
) -> None:
    monkeypatch.setenv(SCORES_TIER_SOLVE_BACKEND_ENV, "process")
    monkeypatch.setattr("api.compute.backend_runtime.process_is_frozen", lambda: True)
    player_id = inference_target_player_id(sample_turn)
    run = _register_run(sample_turn, player_id=player_id)
    ctx = _open_evidence_ctx(sample_turn)
    wire = build_scores_tier_solve_job_wire(
        _scores_scope(sample_turn, player_id),
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    assert set(wire) == _THREAD_IDENTITY_KEYS
    assert wire[WIRE_RUN_ID] == run.run_id


def test_orchestration_skip_stays_off_the_process_pool():
    skip = {
        "runId": None,
        WIRE_EVIDENCE_CLOSED: True,
        WIRE_ORCHESTRATION_SKIP: True,
    }
    result = orchestration_plane_skip_result(skip)
    assert result is not None
    assert result.outcome == "complete"
    assert orchestration_plane_skip_result({"runId": "live"}) is None
    with pytest.raises(RuntimeError, match="orchestration plane"):
        run_sat_search_session(skip)


def test_apply_helper_accepts_step_result_or_payload_dict(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    steps = (_tiny_policy_step("a"), _tiny_policy_step("b"))
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=steps),
    )
    continued = PolicyLadderState(policy_steps=steps, next_step_index=1)
    apply_scores_tier_solve_step_result(
        parent,
        StepResult(outcome="continue", payload={WIRE_LADDER_STATE: continued}),
    )
    assert parent.ladder_state is continued
    completed = PolicyLadderState(policy_steps=steps, ladder_complete=True)
    apply_scores_tier_solve_step_result(parent, {WIRE_LADDER_STATE: completed})
    assert parent.ladder_state is completed


@pytest.mark.parametrize("backend", ["thread", "process"])
def test_wire_build_applies_continue_snapshot_before_next_dispatch(
    sample_turn,
    monkeypatch,
    backend: str,
) -> None:
    if backend == "process":
        _opt_in_process_backend(monkeypatch)
    else:
        monkeypatch.delenv(SCORES_TIER_SOLVE_BACKEND_ENV, raising=False)
    player_id = inference_target_player_id(sample_turn)
    steps = (_tiny_policy_step("a"), _tiny_policy_step("b"))
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=steps),
    )
    continued = PolicyLadderState(policy_steps=steps, next_step_index=1)
    ctx = _open_evidence_ctx(sample_turn)
    kwargs = {
        "dependency_outputs": DependencyOutputs(),
        "ctx": ctx,
        "node_result_wire": {
            WIRE_RUN_ID: parent.run_id,
            WIRE_LADDER_STATE: continued,
        },
    }
    wire = build_scores_tier_solve_job_wire(_scores_scope(sample_turn, player_id), **kwargs)
    assert parent.ladder_state is continued
    assert parent.ladder_state.next_step_index == 1
    assert wire[WIRE_RUN_ID] == parent.run_id
    assert WIRE_LADDER_STATE not in wire


def test_persist_without_run_id_fails_even_when_scope_has_row_run(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(sample_turn, player_id=player_id)
    scope = _scores_scope(sample_turn, player_id)
    ctx = _open_evidence_ctx(sample_turn)
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="missing runId",
    )
    with pytest.raises(TypeError, match="missing string runId"):
        ScoresPersistencePolicy().persist(ctx, scope, {"rowComplete": row_complete})
    assert get_row_run_for_scope(scope) is parent


def test_persist_echoed_run_id_applies_ladder_and_writes(
    sample_turn,
    memory_backend,
) -> None:
    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=()),
    )
    snapshot = PolicyLadderState(policy_steps=(), ladder_complete=True)
    row_persistence = InferenceRowPersistenceService(memory_backend)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={
            SCORES_ANALYTIC_ID: ScoresExportContext(persistence=row_persistence),
        },
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
    )
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="echoed runId persist",
    )
    ScoresPersistencePolicy().persist(
        ctx,
        _scores_scope(sample_turn, player_id),
        {
            WIRE_RUN_ID: parent.run_id,
            WIRE_LADDER_STATE: snapshot,
            "rowComplete": row_complete,
        },
    )
    assert parent.ladder_state is snapshot
    stored = row_persistence.get_row(
        sample_turn.game.id,
        sample_turn.player.id,
        sample_turn.settings.turn,
        player_id,
    )
    assert stored is not None
    assert stored.summary == "echoed runId persist"


def test_parent_mapper_continue_from_incomplete_leaf_snapshot(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    steps = (_tiny_policy_step("a"), _tiny_policy_step("b"))
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=steps),
    )
    continued = PolicyLadderState(policy_steps=steps, next_step_index=1)
    snapshot = {WIRE_RUN_ID: parent.run_id, WIRE_LADDER_STATE: continued}
    mapped = map_scores_tier_solve_remote_result(_scores_scope(sample_turn, player_id), snapshot)
    assert mapped.outcome == "continue"
    assert parent.ladder_state is continued
    assert mapped.payload[WIRE_RUN_ID] == parent.run_id
    assert coerce_step_result(snapshot).outcome == "persist"


def test_parent_mapper_persist_from_complete_leaf_snapshot(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=()),
    )
    completed = PolicyLadderState(policy_steps=(), ladder_complete=True)
    snapshot = {WIRE_RUN_ID: parent.run_id, WIRE_LADDER_STATE: completed}
    mapped = map_scores_tier_solve_remote_result(_scores_scope(sample_turn, player_id), snapshot)
    assert mapped.outcome == "persist"
    assert parent.ladder_state is completed
    assert isinstance(mapped.payload, dict)
    assert mapped.payload[WIRE_RUN_ID] == parent.run_id
    assert mapped.payload["rowComplete"] is not None


def test_parent_mapper_soft_defers_missing_ladder_snapshot(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(sample_turn, player_id=player_id)
    snapshot = {WIRE_RUN_ID: parent.run_id}
    mapped = map_scores_tier_solve_remote_result(_scores_scope(sample_turn, player_id), snapshot)
    assert mapped.outcome == "waiting_deps"
    assert mapped.wait_recovery is None


def test_parent_mapper_fails_loud_on_sat_session_result(sample_turn) -> None:
    player_id = inference_target_player_id(sample_turn)
    session_result = SatSearchCollectionResult(
        assignments=[{"x": 5, "y": 0}],
        last_solver_status=4,
        last_solver_status_name="OPTIMAL",
        stopped_reason="max_solutions",
        time_limited=False,
        tier_max_objective=None,
    ).as_wire()
    with pytest.raises(RuntimeError, match=_PROCESS_UNWIRED):
        map_scores_tier_solve_remote_result(
            _scores_scope(sample_turn, player_id),
            session_result,
        )


def test_parent_mapper_uses_parent_row_run_for_ladder_complete(sample_turn) -> None:
    from api.analytics.military_score_inference.inference_row_runner import (
        outcome_after_ladder_complete,
    )

    player_id = inference_target_player_id(sample_turn)
    parent = _register_run(
        sample_turn,
        player_id=player_id,
        ladder=PolicyLadderState(policy_steps=()),
    )
    parent.session.fleet_torp_input_status = "applied"
    captured: dict[str, object] = {}

    def spy(run, state, observation, turn):
        captured["run"] = run
        captured["fleet_torp"] = run.session.fleet_torp_input_status
        return outcome_after_ladder_complete(run, state, observation, turn)

    snapshot = {
        WIRE_RUN_ID: parent.run_id,
        WIRE_LADDER_STATE: PolicyLadderState(policy_steps=(), ladder_complete=True),
    }
    with patch(
        "api.analytics.scores.compute_orchestration.outcome_after_ladder_complete",
        spy,
    ):
        mapped = map_scores_tier_solve_remote_result(
            _scores_scope(sample_turn, player_id),
            snapshot,
        )
    assert captured["run"] is parent
    assert captured["fleet_torp"] == "applied"
    assert mapped.outcome == "persist"
