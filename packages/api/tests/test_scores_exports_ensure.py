"""Ensure-export tests for scores analytic exports."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import schedule_inference_row
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_STOPPED
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_services import ScoresExportContext
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


def test_ensure_no_op_when_prior_turn_inference_non_persistable(sample_turn, persistence):
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

    stopped_inference = {
        "playerId": player_id,
        "status": STATUS_STOPPED,
        "summary": "stopped",
        "solutionCount": 1,
        "isComplete": True,
        "solutions": [],
        "diagnostics": {"turn": 110},
    }
    with patch(
        "api.analytics.scores.export_precedence.get_scores_row_inference",
        return_value=stopped_inference,
    ):
        EXPORT_CATALOG.ensure_export(ctx, scope)

    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None


def test_probe_after_non_persistable_prior_ensure_omits_missing_step(sample_turn, persistence):
    """After ctx.query ensure, is_scope_ensured skips the walk even when not persisted."""
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
    stopped_inference = {
        "playerId": player_id,
        "status": STATUS_STOPPED,
        "summary": "stopped",
        "solutionCount": 1,
        "isComplete": True,
        "solutions": [],
        "diagnostics": {"turn": 110},
    }
    with patch(
        "api.analytics.scores.export_precedence.get_scores_row_inference",
        return_value=stopped_inference,
    ):
        result = ctx.query(
            "scores",
            ["$.meta.searchStatus"],
            {"turn": 110, "player_id": player_id},
            force_inline_ensure=True,
        )

    assert result.status == "ok"
    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is False
    assert EXPORT_CATALOG.is_ensure_satisfied is not None
    assert EXPORT_CATALOG.is_ensure_satisfied(ctx, scope) is False

    probe = ctx.probe("scores", {"turn": 110, "player_id": player_id})
    assert probe.status == "ok"
    assert probe.total_missing == 0
    assert probe.missing_steps == ()


def test_ensure_schedules_inference_row_on_current_turn(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
    ctx = query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )
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
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )
    EXPORT_CATALOG.ensure_export(ctx, scope)

    run_after = scheduler.row_run_for_player(stream_scope, player_id)
    assert run_after is run_before


def test_ensure_no_op_when_row_persisted_stopped(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_STOPPED,
            summary="stopped",
            solution_count=1,
            is_complete=True,
            solutions=[],
        ),
    )
    ctx = query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )

    EXPORT_CATALOG.ensure_export(ctx, scope)

    assert scheduler.row_run_for_player(stream_scope, player_id) is None


def test_probe_omits_stopped_persisted_row(sample_turn, persistence):
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
            solutions=[],
        ),
    )
    ctx = query_context(sample_turn, persistence=persistence)

    probe = ctx.probe("scores", {"player_id": player_id})

    assert probe.status == "ok"
    assert probe.total_missing == 0
    assert probe.missing_steps == ()


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
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )

    EXPORT_CATALOG.ensure_export(ctx, scope)

    assert scheduler.row_run_for_player(stream_scope, player_id) is None
