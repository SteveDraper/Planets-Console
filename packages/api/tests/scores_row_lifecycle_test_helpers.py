"""Shared helpers for scores row-lifecycle cancel / detach / preempt tests."""

from __future__ import annotations

import threading
import time

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_rows import (
    ScheduledInferenceRow,
    schedule_inference_row,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)

from tests.scores_exports_helpers import minimal_stream_query_context


def _session_for_player(
    sample_turn,
    *,
    player_id: int,
    game_id: int = 628580,
    perspective: int = 1,
) -> InferenceRowStreamSession:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    return InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=game_id,
        perspective=perspective,
        turn_number=sample_turn.settings.turn,
        query_context=minimal_stream_query_context(
            sample_turn,
            game_id=game_id,
            perspective=perspective,
        ),
    )


def _stream_scope(sample_turn) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def _schedule_player_row(
    scheduler: InferenceRowScheduler,
    sample_turn,
    *,
    player_id: int,
    stream_token: str,
) -> ScheduledInferenceRow:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=1,
        stream_token=stream_token,
        query_context=minimal_stream_query_context(sample_turn),
    ).row
    scheduler.accept_pending_run(scheduled.session.run_id)
    return scheduled


def _attach_active_table_stream(
    sample_turn,
    scheduler: InferenceRowScheduler,
    player_ids: tuple[int, ...],
) -> tuple[
    InferenceTableStreamController,
    dict[int, ScheduledInferenceRow],
    threading.Event,
]:
    scope = _stream_scope(sample_turn)
    stream_token = scheduler.begin_scope(scope)
    controller = InferenceTableStreamController(
        scope=scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=player_ids,
        scheduler=scheduler,
        game_id=628580,
        perspective=1,
        query_context=minimal_stream_query_context(sample_turn),
    )

    for player_id in player_ids:
        scheduled = _schedule_player_row(
            scheduler,
            sample_turn,
            player_id=player_id,
            stream_token=stream_token,
        )
        controller.register_scheduled_row(player_id, scheduled)

    controller.attach()
    return (
        controller,
        controller.scheduled_rows,
        controller.wake_multiplex,
    )


def _wait_until(predicate, *, timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def _patch_scores_dag_without_fleet_deps(monkeypatch) -> None:
    """Isolate scores RowRun from fleet ``ENSURE_DEPENDENCIES``.

    Stubs DAG plan to a scores-only node and skips chain-fill. Prepare walks the
    real catalog with ``force_root`` (entry ``step_kind``), which would otherwise
    demand-load ``fleet@T-1`` for single-turn fixtures that never plan fleet.
    """
    patch_scores_only_dag(monkeypatch)
    monkeypatch.setattr(
        "api.compute.orchestrator_submission.prepare_dependency_chain_turns",
        lambda *_args, **_kwargs: None,
    )


def patch_scores_only_dag(monkeypatch) -> None:
    """Plan a scores submit as its root node alone; every other analytic plans for real."""
    from api.compute.dag import PlannedComputeNode
    from api.compute.dag import plan_compute_dag as real_plan
    from api.compute.scope import normalize_export_scope_to_compute_scope

    def scores_only_dag(
        ctx,
        analytic_id,
        export_scope,
        *,
        compute_registry,
        force_root=False,
        **kwargs,
    ):
        if analytic_id != "scores":
            return real_plan(
                ctx,
                analytic_id,
                export_scope,
                compute_registry=compute_registry,
                force_root=force_root,
                **kwargs,
            )
        registration = compute_registry[analytic_id]
        scope = normalize_export_scope_to_compute_scope(
            export_scope,
            analytic_id=analytic_id,
            scope_key_spec=registration.scope_key_spec,
        )
        return (
            PlannedComputeNode(
                scope=scope,
                export_scope=export_scope,
                dependency_scopes=(),
            ),
        )

    monkeypatch.setattr("api.compute.orchestrator_submission.plan_compute_dag", scores_only_dag)
