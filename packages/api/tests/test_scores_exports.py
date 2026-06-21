"""Golden tests for scores analytic exports: registry, queries, and wire helpers."""

from __future__ import annotations

import pytest
from api.analytics.export_context import make_analytic_query_context
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
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_precedence import (
    classify_scores_export,
    is_scores_inference_ensure_satisfied,
    resolve_scores_export,
    resolve_scores_export_payload,
)
from api.analytics.scores.export_snapshot import ScoresInferenceSnapshot
from api.analytics.scores.export_wire import (
    ranked_solutions_from_wire,
    solutions_diagnostics_from_wire_complete_event,
)
from api.analytics.scores.exports import EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.scores_exports_helpers import (
    first_player_id,
    first_turn_from,
    inference_solution,
    materialize_scores_tree,
    put_persisted_row,
    query_context,
    schedule_row_with_ladder,
    ship_build_wire,
    stream_scope_for_turn,
)


def test_export_registry_includes_non_empty_scores_catalog():
    catalog = EXPORT_CATALOG
    assert catalog.analytic_id == "scores"
    assert not catalog.is_empty
    assert catalog.ensure_dependencies == ()
    assert catalog.materialize_export_tree is not None
    assert catalog.ensure_export is not None


def test_complete_empty_solutions_returns_path_none(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="no builds",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    ctx = query_context(sample_turn, persistence=persistence)
    result = ctx.query(
        "scores",
        ["$.solutions[0]", "$.meta.searchStatus"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].kind == "value"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.solutions[0]"].kind == "none"


def test_invalid_scope_without_player_id(sample_turn):
    ctx = query_context(sample_turn)
    result = ctx.query("scores", ["$.solutions"])
    assert result.status == "unavailable"
    assert result.reason == "invalid_scope"


def test_ranked_solutions_from_wire_orders_by_objective_value():
    solutions = ranked_solutions_from_wire(
        [
            {
                "objectiveValue": 10,
                "actions": [],
                "shipBuilds": [{"hullId": 1}],
            },
            {
                "objectiveValue": 99,
                "actions": [],
                "shipBuilds": [{"hullId": 2}],
            },
        ]
    )
    assert solutions[0]["objectiveValue"] == 99
    assert solutions[1]["objectiveValue"] == 10


def test_solutions_diagnostics_from_wire_complete_event():
    solutions, diagnostics, solutions_held = solutions_diagnostics_from_wire_complete_event(
        {
            "type": "complete",
            "status": STATUS_EXACT,
            "summary": "wire",
            "solutionCount": 1,
            "isComplete": True,
            "solutions": [
                {
                    "objectiveValue": 55,
                    "actions": [],
                    "shipBuilds": [{"hullId": 7}],
                }
            ],
            "diagnostics": {"note": "cached"},
        }
    )
    assert solutions_held == 1
    assert solutions[0]["objectiveValue"] == 55
    assert diagnostics == {"note": "cached"}


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
    payload = resolve_scores_export_payload(resolve_scores_export(snapshot))
    assert payload.search_status == "complete"
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
    payload = resolve_scores_export_payload(resolve_scores_export(snapshot))
    assert payload.search_status == "in_progress"
    assert payload.solutions_held == 1


def test_resolve_search_status_matches_payload_status(sample_turn):
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
    classification = classify_scores_export(snapshot)
    assert classification.search_status == resolve_scores_export_payload(resolved).search_status
    assert classification.search_status == "in_progress"


def test_classify_search_status_does_not_materialize_solutions(sample_turn):
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
    assert classify_scores_export(snapshot).search_status == "in_progress"


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
    payload = resolve_scores_export_payload(resolve_scores_export(snapshot))
    assert payload.search_status == "complete"
    assert payload.solutions_held == 1
    assert payload.solutions[0]["shipBuilds"][0]["hullId"] == 88
    assert payload.diagnostics == {"source": "cached_admission"}


def test_top_solution_query_returns_full_build(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="multi-ship",
            solution_count=1,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 80,
                    "actions": [
                        {
                            "actionId": "planet_defense_posts_added_total",
                            "label": "Defense",
                            "count": 2,
                        }
                    ],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="ship-a",
                            label="Freighter A",
                            hull_id=10,
                            engine_id=1,
                        ),
                        ship_build_wire(
                            combo_id="ship-b",
                            label="Freighter B",
                            hull_id=11,
                            engine_id=2,
                        ),
                    ],
                }
            ],
        ),
    )
    ctx = query_context(sample_turn, persistence=persistence)
    result = ctx.query(
        "scores",
        ["$.solutions[0].shipBuilds", "$.solutions[0].actions"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    ship_builds = result.paths["$.solutions[0].shipBuilds"].value
    actions = result.paths["$.solutions[0].actions"].value
    assert len(ship_builds) == 2
    assert ship_builds[0]["hullId"] == 10
    assert ship_builds[1]["hullId"] == 11
    assert actions[0]["count"] == 2


def test_first_turn_materializes_complete_without_ensure(sample_turn):
    first_turn = first_turn_from(sample_turn)
    player_id = first_player_id(first_turn)

    def load_turn(turn_number: int):
        if turn_number == 1:
            return first_turn
        return None

    ctx = make_analytic_query_context(
        first_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
    )
    result = ctx.query(
        "scores",
        ["$.meta.searchStatus", "$.solutions[0]"],
        {"player_id": player_id},
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.solutions[0]"].kind == "none"


@pytest.mark.parametrize(
    ("snapshot", "expected_branch", "ensure_satisfied", "search_status"),
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
    search_status: str,
):
    resolved = resolve_scores_export(snapshot)
    classification = classify_scores_export(snapshot)
    assert classification.branch == expected_branch
    assert is_scores_inference_ensure_satisfied(resolved) is ensure_satisfied
    payload = resolve_scores_export_payload(resolved)
    assert payload.search_status == search_status
    assert (payload.search_status == "complete") == (search_status == "complete")


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
    classification = classify_scores_export(snapshot)
    assert classification.branch == "scheduler"
    assert is_scores_inference_ensure_satisfied(resolved) is True
    payload = resolve_scores_export_payload(resolved)
    assert payload.search_status == "in_progress"
    assert payload.search_status != "complete"


def test_scheduler_branch_surfaces_ladder_diagnostics(sample_turn):
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
    payload = resolve_scores_export_payload(resolve_scores_export(snapshot))
    assert payload.diagnostics is not None
    assert payload.diagnostics["turn"] == sample_turn.settings.turn
    assert payload.diagnostics["solver"]["source"] == "scheduler_ladder"

    ctx = query_context(sample_turn, scheduler=scheduler)
    result = ctx.query(
        "scores",
        ["$.diagnostics.solver.source", "$.meta.searchStatus"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "in_progress"
    assert result.paths["$.diagnostics.solver.source"].value == "scheduler_ladder"

    tree, _scope = materialize_scores_tree(ctx, player_id)
    assert tree["diagnostics"]["solver"]["source"] == "scheduler_ladder"
