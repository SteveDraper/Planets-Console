"""Materialization tree tests for scores analytic exports."""

from __future__ import annotations

from api.analytics.export_context import make_analytic_query_context
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import schedule_inference_row
from api.analytics.military_score_inference.models import InferenceSolutionAction
from api.analytics.military_score_inference.inference_api_payload import STATUS_PLAYER_NOT_FOUND
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_STOPPED
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.exports import EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.scores_exports_helpers import (
    GAME_ID,
    first_player_id,
    first_turn_from,
    inference_solution,
    materialize_scores_tree,
    perspective,
    put_persisted_row,
    query_context,
    schedule_row_with_ladder,
    ship_build_domain,
    ship_build_wire,
    stream_scope_for_turn,
)


def test_fallback_persisted_terminal_status_materializes_complete(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_PLAYER_NOT_FOUND,
            summary="player missing from scoreboard",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
    )
    ctx = query_context(sample_turn, persistence=persistence)
    tree, _scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "complete"
    assert tree["solutions"] == []


def test_turn_not_stored_materializes_not_started(sample_turn):
    player_id = first_player_id(sample_turn)

    def load_turn(_turn_number: int):
        return None

    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
    )
    tree, _scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "not_started"
    assert tree["solutions"] == []


def test_not_started_when_no_persistence_or_scheduler(sample_turn):
    reset_inference_row_scheduler_for_tests()
    player_id = first_player_id(sample_turn)
    ctx = query_context(sample_turn, scheduler=InferenceRowScheduler(worker_count=0))
    tree, _scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "not_started"
    assert tree["solutions"] == []


def test_in_progress_when_scheduler_holds_row(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=50,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense_posts_added_total",
                        label="Planet defense",
                        count=2,
                    ),
                ),
                ship_builds=(
                    ship_build_domain(
                        combo_id="combo-1",
                        label="Small Deep Space Freighter",
                        hull_id=1,
                        engine_id=5,
                    ),
                ),
            )
        ],
    )

    ctx = query_context(sample_turn, scheduler=scheduler)
    tree, _scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "in_progress"
    assert tree["meta"]["solutionsHeld"] == 1
    top = tree["solutions"][0]
    assert top["shipBuilds"][0]["hullId"] == 1
    assert top["actions"][0]["actionId"] == "planet_defense_posts_added_total"


def test_persisted_row_replay_overrides_scheduler_state(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="cached",
            solution_count=1,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 99,
                    "actions": [],
                    "shipBuilds": [
                        ship_build_wire(
                            combo_id="cached-combo",
                            label="Cached hull",
                            hull_id=42,
                            engine_id=7,
                        )
                    ],
                }
            ],
        ),
    )
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=1,
                ship_builds=(
                    ship_build_domain(
                        combo_id="live-combo",
                        label="Live hull",
                        hull_id=1,
                    ),
                ),
            )
        ],
    )

    ctx = query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    result = ctx.query(
        "scores",
        ["$.solutions[0].shipBuilds[0].hullId", "$.meta.searchStatus"],
        {"player_id": player_id},
        force_inline_ensure=True,
    )
    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "complete"
    assert result.paths["$.solutions[0].shipBuilds[0].hullId"].value == 42


def test_paused_when_globally_paused_on_active_stream(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
    scheduler.begin_scope(stream_scope)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[inference_solution(objective_value=25)],
    )
    scheduler.pause_globally(stream_scope)

    ctx = query_context(sample_turn, scheduler=scheduler)
    tree, _scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "paused"


def test_in_progress_when_scheduler_pre_ladder(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
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
    run = scheduler.row_run_for_player(stream_scope_for_turn(sample_turn), player_id)
    assert run is not None
    run.ladder_state = None

    ctx = query_context(sample_turn, scheduler=scheduler)
    tree, _scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "in_progress"


def test_stopped_when_ladder_time_limited(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=35,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense_posts_added_total",
                        label="Planet defense",
                        count=1,
                    ),
                ),
            )
        ],
        time_limited=True,
        ladder_complete=True,
    )

    ctx = query_context(sample_turn, scheduler=scheduler)
    tree, scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "stopped"
    assert tree["meta"]["solutionsHeld"] == 1
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is False


def test_stopped_when_ladder_last_status_stopped(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    schedule_row_with_ladder(
        scheduler,
        sample_turn,
        player_id,
        merged_solutions=[
            inference_solution(
                objective_value=40,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense_posts_added_total",
                        label="Planet defense",
                        count=1,
                    ),
                ),
            )
        ],
        last_status=STATUS_STOPPED,
    )

    ctx = query_context(sample_turn, scheduler=scheduler)
    tree, scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "stopped"
    assert tree["meta"]["solutionsHeld"] == 1
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is False


def test_stopped_when_persisted_row_stopped(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_STOPPED,
            summary="stopped",
            solution_count=1,
            is_complete=True,
            solutions=[
                {
                    "objectiveValue": 40,
                    "actions": [
                        {
                            "actionId": "planet_defense_posts_added_total",
                            "label": "Planet defense",
                            "count": 1,
                        }
                    ],
                    "shipBuilds": [],
                }
            ],
        ),
    )
    ctx = query_context(sample_turn, persistence=persistence)
    tree, scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "stopped"
    assert tree["meta"]["solutionsHeld"] == 1
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is False


def test_first_turn_immediate_complete_is_persisted(sample_turn):
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
    tree, scope = materialize_scores_tree(ctx, player_id)
    assert tree["meta"]["searchStatus"] == "complete"
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is True
