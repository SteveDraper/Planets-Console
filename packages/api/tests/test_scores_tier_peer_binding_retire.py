"""Peer binding / retire regressions for scores tier RowRun sharing."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.compute_orchestration import run_scores_tier_solve
from api.analytics.scores.tier_row_run_registry import (
    _retire_row_run,
    get_row_run,
    register_row_run,
)

from tests.scores_tier_cross_binding_test_helpers import (
    _outcome_snapshot,
    _scope_for,
    _session,
    _set_scope_node,
    _singleton_orchestrator,
    reset_cross_binding_registries,
)


@pytest.fixture(autouse=True)
def _reset_registries():
    with reset_cross_binding_registries():
        yield


def test_run_scores_tier_solve_continues_when_rowrun_retired(sample_turn) -> None:
    """Missing RowRun must park (rebuild wire on wake), not empty-complete and unlock fleet."""
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    _retire_row_run(run.run_id)

    result = run_scores_tier_solve({"runId": run.run_id})

    assert result.outcome == "park"


def test_run_scores_tier_solve_skip_sentinel_requires_evidence_closed_marker() -> None:
    assert run_scores_tier_solve({"runId": None, "evidenceClosed": True}).outcome == "complete"
    with pytest.raises(RuntimeError, match="open-evidence wait wire"):
        run_scores_tier_solve({"runId": None})


def test_first_peer_complete_keeps_rowrun_while_sibling_running(sample_turn, monkeypatch) -> None:
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)

    orchestrator = _singleton_orchestrator()
    _set_scope_node(
        orchestrator,
        scope,
        state="running",
        priority_band="stream_attached",
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scheduler._runs[run.run_id] = scope

    delivered: list[object] = []
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_resolution."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )

    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="exact",
    )
    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="complete",
            result_wire={"runId": run.run_id, "rowComplete": row_complete},
        ),
    )

    assert get_row_run(run.run_id) is run
    assert run.run_id in scheduler._runs
    assert len(delivered) == 1

    orchestrator._nodes[scope].state = "complete"
    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="complete",
            result_wire={"runId": run.run_id, "rowComplete": row_complete},
        ),
    )

    assert get_row_run(run.run_id) is None
    assert run.run_id not in scheduler._runs
    assert len(delivered) == 1


def test_peer_failure_does_not_retire_while_sibling_running(sample_turn, monkeypatch) -> None:
    session = _session(sample_turn)
    run = RowRun(session)
    register_row_run(run)
    scope = _scope_for(session)

    orchestrator = _singleton_orchestrator()
    _set_scope_node(
        orchestrator,
        scope,
        state="running",
        priority_band="stream_attached",
    )

    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scheduler._runs[run.run_id] = scope

    delivered: list[object] = []
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_resolution."
        "deliver_inference_domain_event_to_open_stream",
        lambda _session, event: delivered.append(event),
    )

    scheduler._on_orchestrator_scope_outcome(
        _outcome_snapshot(
            scope,
            state="failed",
            result_wire={"runId": run.run_id},
            error=RuntimeError("peer boom"),
        ),
    )

    assert get_row_run(run.run_id) is run
    assert delivered == []
