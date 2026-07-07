"""Scores analytic compute orchestrator registration surface (minimal until #200)."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.compute.profile import AnalyticComputeProfile, ComputeStepSpec
from api.compute.scope import ComputeScope, ScopeKeySpec, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs

SCORES_MATERIALIZE = "materialize"

SCORES_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn", "player_id"))

SCORES_COMPUTE_PROFILE = AnalyticComputeProfile(
    steps=(ComputeStepSpec(step_kind=SCORES_MATERIALIZE, backend="inline"),),
)


def build_scores_materialize_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
) -> dict[str, Any]:
    """Materialize scores export tree on the orchestration plane."""
    from api.analytics.scores.exports import ensure_scores_export, materialize_scores_export_tree

    del dependency_outputs
    if ctx is None:
        raise RuntimeError("scores materialize job wire requires AnalyticQueryContext")
    export_scope = compute_scope_to_export_scope(scope)
    ensure_scores_export(ctx, export_scope)
    tree = materialize_scores_export_tree(ctx, export_scope)
    return {"exportTree": tree}


def run_scores_materialize(job_wire: dict[str, Any]) -> dict[str, Any]:
    """Inline scores step returns the prefetched export tree."""
    return job_wire["exportTree"]


class ScoresPersistencePolicy:
    """Orchestrator persistence hooks for per-player scores inference scopes."""

    def is_satisfied(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> bool:
        from api.analytics.scores.exports import is_scores_export_ensure_satisfied

        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return False
        return is_scores_export_ensure_satisfied(ctx, export_scope)

    def persist(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: object,
    ) -> None:
        del ctx, scope, result_wire

    def invalidate(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> None:
        from api.analytics.scores.export_services import resolve_scores_services

        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return
        services = resolve_scores_services(ctx)
        if services.persistence is None or export_scope.player_id is None:
            return
        services.persistence.delete_row(
            export_scope.game_id,
            export_scope.perspective,
            export_scope.turn,
            export_scope.player_id,
        )

    def invalidation_generation(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
        del ctx, scope
        return 0


def _export_scope_for_compute(scope: ComputeScope) -> ExportScope | None:
    if scope.player_id == "*" or not isinstance(scope.player_id, int):
        return None
    if scope.turn == "*" or not isinstance(scope.turn, int):
        return None
    if scope.perspective == "*" or not isinstance(scope.perspective, int):
        return None
    return ExportScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=scope.player_id,
    )


SCORES_PERSISTENCE_POLICY = ScoresPersistencePolicy()
