"""Ensure-export tests for scores analytic exports."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import schedule_inference_row
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_STOPPED
from api.analytics.scores.exports import EXPORT_CATALOG
from api.serialization.inference_row_persistence import PersistedInferenceRow

from tests.export_chain_test_fixtures import export_chain_query_context, seed_fleet_unwind_through
from tests.scores_exports_helpers import (
    GAME_ID,
    ensure_missing_step,
    first_player_id,
    perspective,
    prior_turn_ensure_context,
    put_persisted_row,
    scores_missing_step,
    scores_query_context,
    stream_scope_for_turn,
)


@pytest.fixture(autouse=True)
def _reset_inference_stream_registry() -> None:
    reset_inference_table_stream_registry_for_tests()
    yield
    reset_inference_table_stream_registry_for_tests()


def _assert_probe_does_not_compute(monkeypatch):
    """Fail the test if probe invokes inference, stream resolution, or payload materialization."""
    from api.analytics.scores import export_precedence, exports
    from api.analytics.scores import export_snapshot as export_snapshot_module

    monkeypatch.setattr(
        exports,
        "resolve_scores_export",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("probe must not resolve scores export payloads")
        ),
    )
    monkeypatch.setattr(
        exports,
        "get_scores_row_inference",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("probe must not run scores row inference")
        ),
    )
    monkeypatch.setattr(
        export_snapshot_module,
        "gather_scores_inference_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("probe must not gather full scores inference snapshots")
        ),
    )
    monkeypatch.setattr(
        export_snapshot_module,
        "resolve_row_stream_admission",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("probe must not resolve live stream admission")
        ),
    )
    monkeypatch.setattr(
        export_precedence,
        "solutions_from_scheduler_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("probe must not materialize scheduler solutions")
        ),
    )


def test_probe_counts_prior_turn_missing_without_computing(sample_turn, persistence, monkeypatch):
    """Probe must count prior-turn ensure work without inference or payload materialization."""
    ctx, scope, player_id, _, _ = prior_turn_ensure_context(sample_turn, persistence)
    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None

    _assert_probe_does_not_compute(monkeypatch)

    probe = ctx.probe("scores", {"turn": 110, "player_id": player_id})

    assert probe.status == "ok"
    missing = scores_missing_step(probe, turn=110, player_id=player_id)
    assert missing.status == "not_persisted"


def test_probe_counts_current_turn_missing_without_computing(sample_turn, persistence, monkeypatch):
    """Probe must count current-turn scheduler attachment without scheduling or materializing."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
        seed_fleet_prerequisites_for=player_id,
    )
    assert scheduler.row_run_for_player(stream_scope, player_id) is None

    _assert_probe_does_not_compute(monkeypatch)

    probe = ctx.probe("scores", {"player_id": player_id})

    assert probe.status == "ok"
    missing = scores_missing_step(probe, turn=sample_turn.settings.turn, player_id=player_id)
    assert missing.status == "not_persisted"
    assert scheduler.row_run_for_player(stream_scope, player_id) is None


def test_ensure_invalidates_materialized_tree_cache(sample_turn, persistence):
    """Materialized tree cached before ensure must not survive scheduler mutation."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    ctx = scores_query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )
    catalog = EXPORT_CATALOG

    tree_before = ctx._materialize_tree("scores", scope, catalog)
    assert tree_before["meta"]["searchStatus"] == "not_started"

    EXPORT_CATALOG.ensure_export(ctx, scope)

    tree_after = ctx._materialize_tree("scores", scope, catalog)
    assert tree_after["meta"]["searchStatus"] == "in_progress"
    assert tree_after is not tree_before


def test_probe_reports_prior_turn_work_without_running_ensure(sample_turn, persistence):
    """Probe must count missing prior-turn work without sync inference or persistence."""
    ctx, scope, player_id, _, _ = prior_turn_ensure_context(sample_turn, persistence)
    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None
    assert EXPORT_CATALOG.is_ensure_satisfied(ctx, scope) is False

    with (
        patch(
            "api.analytics.scores.exports.get_scores_row_inference",
        ) as mock_inference,
        patch(
            "api.analytics.scores.exports.schedule_inference_row",
        ) as mock_schedule,
        patch.object(persistence, "put_row") as mock_put_row,
    ):
        probe = ctx.probe("scores", {"turn": 110, "player_id": player_id})

        mock_inference.assert_not_called()
        mock_schedule.assert_not_called()
        mock_put_row.assert_not_called()

    assert probe.status == "ok"
    missing = scores_missing_step(probe, turn=110, player_id=player_id)
    assert missing.status == "not_persisted"
    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None


def test_probe_reports_current_turn_work_without_scheduling(sample_turn, persistence):
    """Probe must count missing current-turn work without attaching the scheduler."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
        seed_fleet_prerequisites_for=player_id,
    )
    assert scheduler.row_run_for_player(stream_scope, player_id) is None

    with patch(
        "api.analytics.scores.exports.schedule_inference_row",
    ) as mock_schedule:
        probe = ctx.probe("scores", {"player_id": player_id})
        mock_schedule.assert_not_called()

    assert probe.status == "ok"
    scores_missing_step(probe, turn=sample_turn.settings.turn, player_id=player_id)
    assert scheduler.row_run_for_player(stream_scope, player_id) is None


def test_ensure_prior_turn_sync_puts_persistable_row(sample_turn, persistence):
    ctx, scope, player_id, _, _ = prior_turn_ensure_context(sample_turn, persistence)
    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None

    EXPORT_CATALOG.ensure_export(ctx, scope)

    row = persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id)
    assert row is not None
    assert row.status in {STATUS_EXACT, "no_exact_solution"}


def test_ensure_no_op_when_prior_turn_inference_non_persistable(sample_turn, persistence):
    ctx, scope, player_id, _, _ = prior_turn_ensure_context(sample_turn, persistence)
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
        "api.analytics.scores.exports.get_scores_row_inference",
        return_value=stopped_inference,
    ) as mock_inference:
        assert EXPORT_CATALOG.ensure_export(ctx, scope) is True
        mock_inference.assert_called_once()

    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None
    assert EXPORT_CATALOG.is_ensure_satisfied(ctx, scope) is True


def test_probe_after_non_persistable_prior_ensure_omits_missing_step(sample_turn, persistence):
    """After ensure stashes terminal sync admission, probe and is_ensure_satisfied agree."""
    ctx, scope, player_id, _, _ = prior_turn_ensure_context(sample_turn, persistence)
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
        "api.analytics.scores.exports.get_scores_row_inference",
        return_value=stopped_inference,
    ):
        result = ctx.query(
            "scores",
            ["$.meta.searchStatus"],
            {"turn": 110, "player_id": player_id},
            force_inline_ensure=True,
        )

    assert result.status == "ok"
    assert result.paths["$.meta.searchStatus"].value == "stopped"
    assert persistence.get_row(GAME_ID, perspective(sample_turn), 110, player_id) is None
    assert EXPORT_CATALOG.is_persisted is not None
    assert EXPORT_CATALOG.is_persisted(ctx, scope) is False
    assert EXPORT_CATALOG.is_ensure_satisfied is not None
    assert EXPORT_CATALOG.is_ensure_satisfied(ctx, scope) is True

    probe = ctx.probe("scores", {"turn": 110, "player_id": player_id})
    assert probe.status == "ok"
    assert probe.total_missing == 0
    assert probe.missing_steps == ()


def test_ensure_schedules_inference_row_on_current_turn(sample_turn, persistence):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    player_id = first_player_id(sample_turn)
    stream_scope = stream_scope_for_turn(sample_turn)
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        scheduler=scheduler,
        seed_fleet_prerequisites_for=player_id,
    )
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

    ctx = scores_query_context(sample_turn, persistence=persistence, scheduler=scheduler)
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
    ctx = scores_query_context(sample_turn, persistence=persistence, scheduler=scheduler)
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
    ctx = export_chain_query_context(
        sample_turn,
        persistence=persistence,
        seed_fleet_prerequisites_for=player_id,
    )
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

    probe = ctx.probe("scores", {"player_id": player_id})

    assert probe.status == "ok"
    assert probe.total_missing == 0
    assert probe.missing_steps == ()


def test_probe_reports_scores_depends_on_fleet_prior_turn(sample_turn, persistence):
    """Probe must count fleet@N-1 before current-turn scores when the chain is incomplete."""
    player_id = first_player_id(sample_turn)
    turn_number = sample_turn.settings.turn
    prior_turn = turn_number - 1
    ctx = export_chain_query_context(sample_turn, persistence=persistence)
    seed_fleet_unwind_through(ctx, through_turn=prior_turn, player_id=player_id)
    put_persisted_row(
        persistence,
        sample_turn,
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seed",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        host_turn=prior_turn,
    )

    probe = ctx.probe("scores", {"player_id": player_id})

    assert probe.status == "ok"
    assert probe.total_missing == 2
    fleet_step = ensure_missing_step(
        probe,
        analytic_id="fleet",
        turn=prior_turn,
        player_id=player_id,
    )
    scores_step = ensure_missing_step(
        probe,
        analytic_id="scores",
        turn=turn_number,
        player_id=player_id,
    )
    assert fleet_step.status == "not_persisted"
    assert scores_step.status == "not_persisted"
    assert probe.missing_steps.index(fleet_step) < probe.missing_steps.index(scores_step)


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
    ctx = scores_query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    scope = ExportScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )

    EXPORT_CATALOG.ensure_export(ctx, scope)

    assert scheduler.row_run_for_player(stream_scope, player_id) is None
