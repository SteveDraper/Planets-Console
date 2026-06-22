"""Unit tests for scores export precedence and payload resolution."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_INVALID_PROBLEM,
    STATUS_PLAYER_NOT_FOUND,
    STATUS_SOLVER_ERROR,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import CachedCompleteRowAdmission
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.export_precedence import (
    is_scores_inference_ensure_satisfied,
    resolve_scores_export,
)
from api.analytics.scores.export_snapshot import ScoresInferenceSnapshot
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.scores_exports_helpers import (
    first_player_id,
    inference_solution,
    schedule_row_with_ladder,
    ship_build_wire,
    stream_scope_for_turn,
)


@pytest.mark.parametrize(
    "persisted_status",
    [
        STATUS_PLAYER_NOT_FOUND,
        STATUS_INVALID_PROBLEM,
        STATUS_SOLVER_ERROR,
    ],
)
def test_fallback_persisted_terminal_statuses_resolve_complete_without_live_state(
    persisted_status: str,
):
    snapshot = ScoresInferenceSnapshot(
        persisted_row=PersistedInferenceRow(
            status=persisted_status,
            summary=persisted_status,
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        admission=None,
        scheduler_run=None,
        globally_paused=False,
    )
    resolved = resolve_scores_export(snapshot)
    payload = resolved.payload
    assert resolved.decision.search_status == "complete"
    assert payload.solutions == []
    assert payload.solutions_held == 0


def test_active_scheduler_overrides_fallback_persisted_terminal_status(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[inference_solution(objective_value=12)],
    )
    run = scheduler.row_run_for_player(stream_scope_for_turn(sample_turn), player_id)
    assert run is not None

    snapshot = ScoresInferenceSnapshot(
        persisted_row=PersistedInferenceRow(
            status=STATUS_PLAYER_NOT_FOUND,
            summary="player missing from scoreboard",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    resolved = resolve_scores_export(snapshot)
    payload = resolved.payload
    assert resolved.decision.search_status == "in_progress"
    assert payload.solutions_held == 1


def test_scheduler_branch_search_status_in_progress(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[inference_solution(objective_value=50)],
    )
    run = scheduler.row_run_for_player(stream_scope_for_turn(sample_turn), player_id)
    assert run is not None

    snapshot = ScoresInferenceSnapshot(
        persisted_row=None,
        admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    resolved = resolve_scores_export(snapshot)
    assert resolved.decision.search_status == "in_progress"
    _ = resolved.payload


def test_decision_search_status_available_without_payload_materialization(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[inference_solution(objective_value=50)],
    )
    run = scheduler.row_run_for_player(stream_scope_for_turn(sample_turn), player_id)
    assert run is not None

    snapshot = ScoresInferenceSnapshot(
        persisted_row=None,
        admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    assert resolve_scores_export(snapshot).decision.search_status == "in_progress"


def test_cached_complete_admission_resolves_payload_from_event():
    wire_event = {
        "type": "complete",
        "status": STATUS_EXACT,
        "summary": "cached admission",
        "solutionCount": 1,
        "isComplete": True,
        "solutions": [
            {
                "objectiveValue": 77,
                "actions": [],
                "shipBuilds": [
                    ship_build_wire(
                        combo_id="cached-admission-combo",
                        label="Cached admission hull",
                        hull_id=88,
                        engine_id=3,
                    )
                ],
            }
        ],
        "diagnostics": {"source": "cached_admission"},
    }
    snapshot = ScoresInferenceSnapshot(
        persisted_row=None,
        admission=CachedCompleteRowAdmission(event=wire_event),
        scheduler_run=None,
        globally_paused=False,
    )
    resolved = resolve_scores_export(snapshot)
    payload = resolved.payload
    assert resolved.decision.search_status == "complete"
    assert payload.solutions_held == 1
    assert payload.solutions[0]["shipBuilds"][0]["hullId"] == 88
    assert payload.diagnostics == {"source": "cached_admission"}


@pytest.mark.parametrize(
    (
        "snapshot",
        "expected_branch",
        "ensure_satisfied",
        "needs_ensure_work",
        "search_status",
    ),
    [
        (
            ScoresInferenceSnapshot(
                persisted_row=PersistedInferenceRow(
                    status=STATUS_EXACT,
                    summary="exact",
                    solution_count=0,
                    is_complete=True,
                    solutions=[],
                ),
                admission=None,
                scheduler_run=None,
                globally_paused=False,
            ),
            "priority_persisted",
            True,
            False,
            "complete",
        ),
        (
            ScoresInferenceSnapshot(
                persisted_row=None,
                admission=CachedCompleteRowAdmission(
                    event={
                        "type": "complete",
                        "status": STATUS_EXACT,
                        "summary": "admission",
                        "solutionCount": 0,
                        "isComplete": True,
                        "solutions": [],
                    }
                ),
                scheduler_run=None,
                globally_paused=False,
            ),
            "terminal_admission",
            True,
            False,
            "complete",
        ),
        (
            ScoresInferenceSnapshot(
                persisted_row=None,
                admission=None,
                scheduler_run=None,
                globally_paused=False,
            ),
            "empty",
            False,
            True,
            "not_started",
        ),
        (
            ScoresInferenceSnapshot(
                persisted_row=PersistedInferenceRow(
                    status=STATUS_PLAYER_NOT_FOUND,
                    summary="player missing",
                    solution_count=0,
                    is_complete=True,
                    solutions=[],
                ),
                admission=None,
                scheduler_run=None,
                globally_paused=False,
            ),
            "fallback_persisted",
            True,
            False,
            "complete",
        ),
    ],
    ids=[
        "priority_persisted",
        "terminal_admission",
        "empty",
        "fallback_persisted",
    ],
)
def test_ensure_satisfied_tracks_precedence_branch(
    snapshot: ScoresInferenceSnapshot,
    expected_branch: str,
    ensure_satisfied: bool,
    needs_ensure_work: bool,
    search_status: str,
):
    resolved = resolve_scores_export(snapshot)
    assert resolved.decision.branch == expected_branch
    assert resolved.decision.needs_ensure_work is needs_ensure_work
    assert is_scores_inference_ensure_satisfied(resolved) is ensure_satisfied
    assert resolved.decision.search_status == search_status
    _ = resolved.payload


def test_scheduler_branch_ensure_satisfied_without_complete(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[inference_solution(objective_value=12)],
    )
    run = scheduler.row_run_for_player(stream_scope_for_turn(sample_turn), player_id)
    assert run is not None

    snapshot = ScoresInferenceSnapshot(
        persisted_row=None,
        admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    resolved = resolve_scores_export(snapshot)
    assert resolved.decision.branch == "scheduler"
    assert resolved.decision.needs_ensure_work is False
    assert is_scores_inference_ensure_satisfied(resolved) is True
    assert resolved.decision.search_status == "in_progress"
    _ = resolved.payload


def test_scheduler_branch_surfaces_ladder_diagnostics_from_snapshot(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[inference_solution(objective_value=12)],
    )
    run = scheduler.row_run_for_player(stream_scope_for_turn(sample_turn), player_id)
    assert run is not None
    assert run.ladder_state is not None
    run.ladder_state.last_diagnostics = {"source": "scheduler_ladder"}

    snapshot = ScoresInferenceSnapshot(
        persisted_row=None,
        admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    payload = resolve_scores_export(snapshot).payload
    assert payload.diagnostics is not None
    assert payload.diagnostics["turn"] == sample_turn.settings.turn
    assert payload.diagnostics["solver"]["source"] == "scheduler_ladder"
