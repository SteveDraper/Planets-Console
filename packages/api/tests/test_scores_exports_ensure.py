"""Ensure-export tests for scores analytic exports."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.export_context import make_analytic_query_context
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import schedule_inference_row
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.exports import EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.scores_exports_helpers import (
    GAME_ID,
    first_player_id,
    perspective,
    put_persisted_row,
    query_context,
    stream_scope_for_turn,
)


def test_ensure_prior_turn_sync_puts_persistable_row(sample_turn, persistence):
    player_id = first_player_id(sample_turn)
    prior_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=110),
        game=replace(sample_turn.game, turn=110),
    )
    prior_prior_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=109),
        game=replace(sample_turn.game, turn=109),
    )
    stored_turns = {
        109: prior_prior_turn,
        110: prior_turn,
        sample_turn.settings.turn: sample_turn,
    }

    def load_turn(turn_number: int):
        return stored_turns.get(turn_number)

    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={"scores": ScoresExportContext(persistence=persistence)},
    )
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=110,
        player_id=player_id,
    )
    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None

    EXPORT_CATALOG.ensure_export(ctx, scope)

    row = persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id)
    assert row is not None
    assert row.status in {STATUS_EXACT, "no_exact_solution"}


def test_ensure_schedules_inference_row_on_current_turn(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
    ctx = query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})
    assert scheduler.row_run_for_player(stream_scope, player_id) is None

    EXPORT_CATALOG.ensure_export(ctx, scope)

    assert scheduler.row_run_for_player(stream_scope, player_id) is not None


def test_ensure_no_op_when_row_already_scheduled(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
    )
    run_before = scheduler.row_run_for_player(stream_scope, player_id)
    assert run_before is not None

    ctx = query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})
    EXPORT_CATALOG.ensure_export(ctx, scope)

    run_after = scheduler.row_run_for_player(stream_scope, player_id)
    assert run_after is run_before


def test_ensure_no_op_when_row_persisted(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
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
    )
    ctx = query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ctx._resolve_scope({"player_id": player_id})

    EXPORT_CATALOG.ensure_export(ctx, scope)

    assert scheduler.row_run_for_player(stream_scope, player_id) is None
