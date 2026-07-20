"""Shared helpers for scores row-lifecycle cancel / detach / preempt tests."""

from __future__ import annotations

import time

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)


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
    )


def _wait_until(predicate, *, timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def _patch_scores_dag_without_fleet_deps(monkeypatch) -> None:
    from api.compute.dag import PlannedComputeNode
    from api.compute.dag import plan_compute_dag as real_plan
    from api.compute.scope import normalize_export_scope_to_compute_scope

    def scores_only_dag(ctx, analytic_id, export_scope, *, compute_registry, force_root=False):
        if analytic_id != "scores":
            return real_plan(
                ctx,
                analytic_id,
                export_scope,
                compute_registry=compute_registry,
                force_root=force_root,
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
