"""Shared helpers for scores tier cross-binding / park / orphan stream tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Literal

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests
from api.compute.scope import ComputeScope


@contextmanager
def reset_cross_binding_registries():
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_inference_table_stream_registry_for_tests()
    try:
        yield
    finally:
        reset_tier_row_run_registry_for_tests()
        reset_orchestrators_for_tests()
        reset_inference_row_scheduler_for_tests()
        reset_inference_table_stream_registry_for_tests()


def _session(sample_turn) -> InferenceRowStreamSession:
    score = sample_turn.scores[0]
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=sample_turn.settings.turn,
    )


def _scope_for(session: InferenceRowStreamSession) -> ComputeScope:
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=session.game_id,
        perspective=session.perspective,
        turn=session.turn_number,
        player_id=session.player_id,
    )


def _outcome_snapshot(
    scope: ComputeScope,
    *,
    state: Literal["parked", "complete", "failed"],
    result_wire: object | None = None,
    error: BaseException | None = None,
    execution_generation: int = 0,
    park_reason: str | None = None,
) -> ScopeLifecycleSnapshot:
    return ScopeLifecycleSnapshot(
        scope=scope,
        state=state,
        execution_generation=execution_generation,
        result_wire=result_wire,
        error=error,
        park_reason=park_reason,
    )


def _singleton_orchestrator():
    return get_compute_orchestrator()


def _set_scope_node(
    orchestrator,
    scope: ComputeScope,
    *,
    state: str,
    priority_band: str = "background",
    **kwargs: object,
) -> ComputeNodeRun:
    node = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state=state,
        priority_band=priority_band,
        **kwargs,
    )
    orchestrator._nodes[scope] = node
    return node
