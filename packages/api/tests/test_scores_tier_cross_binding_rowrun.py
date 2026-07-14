"""Regression: shared RowRun must survive first peer binding completion."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.compute_orchestration import run_scores_tier_solve
from api.analytics.scores.tier_row_run_registry import (
    get_row_run,
    register_row_run,
    reset_tier_row_run_registry_for_tests,
    unregister_row_run,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun
from api.compute.runtime import orchestrator_for_context, reset_orchestrators_for_tests
from api.compute.scope import ComputeScope


@pytest.fixture(autouse=True)
def _reset_registries():
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()


def _session(sample_turn) -> InferenceRowStreamSession:
    score = sample_turn.scores[0]
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=sample_turn.settings.turn,
    )


def _scope_for(session: InferenceRowStreamSession) -> ComputeScope:
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=session.game_id,
        perspective=session.perspective,
        turn=session.turn_number,
        player_id=session.player_id,
    )


def _peer_orchestrators(sample_turn):
    background_ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={},
    )
    stream_ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={},
    )
    return orchestrator_for_context(background_ctx), orchestrator_for_context(stream_ctx)


def test_run_scores_tier_solve_idempotent_when_rowrun_unregistered(sample_turn) -> None:
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    unregister_row_run(run.run_id)

    result = run_scores_tier_solve({"runId": run.run_id})

    assert result.outcome == "complete"


def test_first_peer_complete_keeps_rowrun_while_sibling_running(sample_turn, monkeypatch) -> None:
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)

    background, stream = _peer_orchestrators(sample_turn)
    background._nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="complete",
        priority_band="background",
    )
    stream._nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        priority_band="stream_attached",
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scheduler._runs[run.run_id] = scope

    delivered: list[object] = []
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_scheduler."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )

    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="exact",
    )
    completed_node = SimpleNamespace(
        state="complete",
        result_wire={"runId": run.run_id, "rowComplete": row_complete},
        error=None,
    )

    scheduler._on_orchestrator_node_complete(scope, completed_node)

    assert get_row_run(run.run_id) is run
    assert run.run_id in scheduler._runs
    assert len(delivered) == 1

    stream._nodes[scope].state = "complete"
    scheduler._on_orchestrator_node_complete(scope, completed_node)

    assert get_row_run(run.run_id) is None
    assert run.run_id not in scheduler._runs
    assert len(delivered) == 1


def test_peer_failure_does_not_unregister_while_sibling_running(sample_turn, monkeypatch) -> None:
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)

    background, stream = _peer_orchestrators(sample_turn)
    background._nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="failed",
        priority_band="background",
        error=RuntimeError("peer boom"),
    )
    stream._nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        priority_band="stream_attached",
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scheduler._runs[run.run_id] = scope

    delivered: list[object] = []
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_scheduler."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )

    failed_node = SimpleNamespace(
        state="failed",
        result_wire={"runId": run.run_id},
        error=RuntimeError("peer boom"),
    )
    scheduler._on_orchestrator_node_complete(scope, failed_node)

    assert get_row_run(run.run_id) is run
    assert delivered == []
