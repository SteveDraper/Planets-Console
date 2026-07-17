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
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
)
from api.analytics.scores.export_precedence import (
    is_durable_turn_evidence_row_status,
    resolve_scores_export,
)
from api.analytics.scores.export_snapshot import ScoresInferenceSnapshot
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.scores_exports_helpers import (
    first_player_id,
    inference_solution,
    minimal_scores_export_resolution_context,
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
    sample_turn,
):
    snapshot = ScoresInferenceSnapshot(
        persisted_row=PersistedInferenceRow(
            status=persisted_status,
            summary=persisted_status,
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        stream_admission=None,
        ensure_sync_admission=None,
        scheduler_run=None,
        globally_paused=False,
    )
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
    payload = resolved.payload
    assert resolved.decision.search_status == "complete"
    assert payload.solutions == []
    assert payload.solutions_held == 0


def test_persisted_time_limited_is_priority_stopped_and_closes_turn_evidence(sample_turn):
    """TIME_LIMITED on disk matches host-turn stopped semantics and closes evidence."""
    assert is_durable_turn_evidence_row_status(STATUS_TIME_LIMITED)
    snapshot = ScoresInferenceSnapshot(
        persisted_row=PersistedInferenceRow(
            status=STATUS_TIME_LIMITED,
            summary="time limited",
            solution_count=0,
            is_complete=False,
            solutions=[],
        ),
        stream_admission=None,
        ensure_sync_admission=None,
        scheduler_run=None,
        globally_paused=False,
    )
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
    assert resolved.decision.branch == "priority_persisted"
    assert resolved.decision.search_status == "stopped"
    assert resolved.decision.is_turn_evidence_closed is True


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
        stream_admission=None,
        ensure_sync_admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
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
        stream_admission=None,
        ensure_sync_admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
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
        stream_admission=None,
        ensure_sync_admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    assert (
        resolve_scores_export(
            snapshot,
            resolution_context=minimal_scores_export_resolution_context(sample_turn),
        ).decision.search_status
        == "in_progress"
    )


def test_cached_complete_admission_resolves_payload_from_event(sample_turn):
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
        stream_admission=CachedCompleteRowAdmission(event=wire_event),
        ensure_sync_admission=None,
        scheduler_run=None,
        globally_paused=False,
    )
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
    payload = resolved.payload
    assert resolved.decision.search_status == "complete"
    assert payload.solutions_held == 1
    assert payload.solutions[0]["shipBuilds"][0]["hullId"] == 88
    assert payload.diagnostics == {"source": "cached_admission"}


def test_stopped_terminal_admission_resolves_stopped_search_status(sample_turn):
    wire_event = {
        "type": "complete",
        "status": STATUS_STOPPED,
        "summary": "stopped",
        "solutionCount": 1,
        "isComplete": True,
        "solutions": [],
        "diagnostics": {"turn": 110},
    }
    snapshot = ScoresInferenceSnapshot(
        persisted_row=None,
        stream_admission=CachedCompleteRowAdmission(event=wire_event),
        ensure_sync_admission=None,
        scheduler_run=None,
        globally_paused=False,
    )
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
    assert resolved.decision.branch == "terminal_admission"
    assert resolved.decision.search_status == "stopped"


def test_ensure_sync_admission_overrides_stream_admission_for_terminal_resolution(sample_turn):
    stream_event = {
        "type": "complete",
        "status": STATUS_EXACT,
        "summary": "stream",
        "solutionCount": 1,
        "isComplete": True,
        "solutions": [{"objectiveValue": 10, "actions": [], "shipBuilds": []}],
    }
    ensure_sync_event = {
        "type": "complete",
        "status": STATUS_STOPPED,
        "summary": "ensure sync",
        "solutionCount": 0,
        "isComplete": True,
        "solutions": [],
        "diagnostics": {"source": "ensure_sync"},
    }
    snapshot = ScoresInferenceSnapshot(
        persisted_row=None,
        stream_admission=CachedCompleteRowAdmission(event=stream_event),
        ensure_sync_admission=ImmediateRowAdmission(events=(ensure_sync_event,)),
        scheduler_run=None,
        globally_paused=False,
    )
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
    assert resolved.decision.branch == "terminal_admission"
    assert resolved.decision.search_status == "stopped"
    assert resolved.payload.diagnostics == {"source": "ensure_sync"}


@pytest.mark.parametrize(
    (
        "snapshot",
        "expected_branch",
        "ensure_satisfied",
        "needs_ensure_work",
        "search_status",
        "turn_evidence_closed",
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
                stream_admission=None,
                ensure_sync_admission=None,
                scheduler_run=None,
                globally_paused=False,
            ),
            "priority_persisted",
            True,
            False,
            "complete",
            True,
        ),
        (
            ScoresInferenceSnapshot(
                persisted_row=None,
                stream_admission=CachedCompleteRowAdmission(
                    event={
                        "type": "complete",
                        "status": STATUS_EXACT,
                        "summary": "admission",
                        "solutionCount": 0,
                        "isComplete": True,
                        "solutions": [],
                    }
                ),
                ensure_sync_admission=None,
                scheduler_run=None,
                globally_paused=False,
            ),
            "terminal_admission",
            True,
            False,
            "complete",
            True,
        ),
        (
            ScoresInferenceSnapshot(
                persisted_row=None,
                stream_admission=None,
                ensure_sync_admission=None,
                scheduler_run=None,
                globally_paused=False,
            ),
            "empty",
            False,
            True,
            "not_started",
            False,
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
                stream_admission=None,
                ensure_sync_admission=None,
                scheduler_run=None,
                globally_paused=False,
            ),
            "fallback_persisted",
            True,
            False,
            "complete",
            True,
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
    turn_evidence_closed: bool,
    sample_turn,
):
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
    assert resolved.decision.branch == expected_branch
    assert resolved.decision.needs_ensure_work is needs_ensure_work
    assert resolved.decision.is_ensure_satisfied is ensure_satisfied
    assert resolved.decision.is_turn_evidence_closed is turn_evidence_closed
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
        stream_admission=None,
        ensure_sync_admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    resolved = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    )
    assert resolved.decision.branch == "scheduler"
    assert resolved.decision.needs_ensure_work is False
    assert resolved.decision.is_ensure_satisfied is True
    assert resolved.decision.is_turn_evidence_closed is False
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
        stream_admission=None,
        ensure_sync_admission=None,
        scheduler_run=run,
        globally_paused=False,
    )
    payload = resolve_scores_export(
        snapshot,
        resolution_context=minimal_scores_export_resolution_context(sample_turn),
    ).payload
    assert payload.diagnostics is not None
    assert payload.diagnostics["turn"] == sample_turn.settings.turn
    assert payload.diagnostics["solver"]["source"] == "scheduler_ladder"


def test_functional_backfill_resolves_host_turn_targets_without_diagnostics(sample_turn):
    from dataclasses import replace

    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.export_types import ExportScope
    from api.analytics.military_score_inference.analytic import infer_military_score_build
    from api.analytics.military_score_inference.host_turn_targets import (
        host_turn_targets_from_wire_event,
    )
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.exports import held_scores_for_scope
    from api.services.inference_row_persistence_service import InferenceRowPersistenceService
    from api.storage.memory_asset import MemoryAssetBackend
    from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

    from tests.inference_corpus.fixtures import load_turn_fixture

    turn_three = load_turn_fixture("628580/1/turns/3.json")
    turn_two = replace(turn_three, settings=replace(turn_three.settings, turn=2))
    turn_two = replace(
        turn_two,
        scores=[replace(score, turn=2) for score in turn_two.scores],
    )
    player_id = 11
    score = next(entry for entry in turn_three.scores if entry.ownerid == player_id)
    inference_payload = infer_military_score_build(score, turn_three)
    host_turn_targets = list(
        host_turn_targets_from_wire_event(
            inference_api_payload_to_wire_complete(inference_payload),
        ),
    )
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
        if turn_number == 2:
            return turn_two
        if turn_number == 3:
            return turn_three
        return None

    ctx = make_analytic_query_context(
        turn_two,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={"scores": ScoresExportContext(persistence=persistence)},
    )
    resolved = held_scores_for_scope(
        ctx,
        ExportScope(game_id=628580, perspective=1, turn=2, player_id=player_id),
        turn=turn_two,
    )
    assert resolved.decision.branch == "functional_backfill"
    assert resolved.payload.diagnostics is None
    assert resolved.payload.solutions
    assert resolved.payload.solutions_held > 0


def test_resolve_scores_export_resolves_functional_payload_once(monkeypatch, sample_turn):
    from api.analytics.scores import export_precedence

    call_count = 0
    original = export_precedence.resolve_functional_host_turn_payload

    def counting_resolve(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        export_precedence,
        "resolve_functional_host_turn_payload",
        counting_resolve,
    )

    snapshot = ScoresInferenceSnapshot(
        persisted_row=PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="exact",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        stream_admission=None,
        ensure_sync_admission=None,
        scheduler_run=None,
        globally_paused=False,
    )
    context = minimal_scores_export_resolution_context(
        sample_turn,
        scoreboard_turn=sample_turn.settings.turn,
    )
    resolve_scores_export(snapshot, resolution_context=context)
    assert call_count == 1
