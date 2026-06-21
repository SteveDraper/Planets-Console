"""Export catalog for the scores turn analytic."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.military_score_inference.inference_stream_rows import schedule_inference_row
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
)
from api.analytics.scores.export_precedence import (
    ScoresExportResolved,
    build_scores_export_materialized_tree,
    is_scores_export_authoritatively_persisted,
    is_scores_inference_ensure_satisfied,
    resolve_scores_export,
    sync_persist_empty_branch,
)
from api.analytics.scores.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.scores.export_services import ScoresExportContext, resolve_scores_services
from api.analytics.scores.export_snapshot import (
    gather_scores_inference_snapshot,
    scores_inference_stream_scope,
)
from api.analytics.scores_assets import ANALYTIC_ID
from api.errors import ValidationError
from api.models.game import TurnInfo

PATH_PREFIX_SCOPE_RULES = (
    PathPrefixScopeRule(prefix="$.solutions", requires=("player_id",)),
    PathPrefixScopeRule(prefix="$.diagnostics", requires=("player_id",)),
    PathPrefixScopeRule(prefix="$.hullCatalogMask", requires=("player_id",)),
)

ORDERING_SEMANTICS = {
    "$.solutions": (
        "Descending by objectiveValue (inference solution rank weight / UI "
        "Plausibility). Higher values mean more plausible on a pseudo "
        "log-likelihood scale derived from build priors plus ranking heuristics. "
        "$.solutions[0] is the top held explanation."
    ),
}

ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = ()


def _scores_resolved(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    turn: TurnInfo | None = None,
) -> tuple[ScoresExportContext, ScoresExportResolved]:
    services = resolve_scores_services(ctx)
    resolved_turn = turn if turn is not None else ctx.load_turn(scope.turn)

    def gather() -> ScoresExportResolved:
        snapshot = gather_scores_inference_snapshot(ctx, services, scope, resolved_turn)
        return resolve_scores_export(snapshot)

    resolved = ctx.export_snapshot_for(ANALYTIC_ID, scope, gather)
    return services, resolved


def is_scores_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if scope.player_id is None:
        return False

    _services, resolved = _scores_resolved(ctx, scope)
    return is_scores_export_authoritatively_persisted(resolved)


def is_scores_export_ensure_satisfied(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if scope.player_id is None:
        return True

    _services, resolved = _scores_resolved(ctx, scope)
    return is_scores_inference_ensure_satisfied(resolved)


def ensure_scores_export(ctx: AnalyticQueryContext, scope: ExportScope) -> None:
    if scope.player_id is None:
        return

    services, resolved = _scores_resolved(ctx, scope)
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return

    if is_scores_inference_ensure_satisfied(resolved):
        return

    # Prior-turn sync ensure may no-op when inference is non-persistable (e.g. stopped).
    # ctx.query still marks the scope ensured after ensure_export returns; probe walks
    # skip re-entry via is_scope_ensured even when is_persisted remains False.
    if scope.turn < ctx.ambient_turn:
        if sync_persist_empty_branch(
            resolved,
            services=services,
            scope=scope,
            turn=turn,
            load_scoreboard_turn=ctx.load_turn,
        ):
            ctx.invalidate_export_snapshot(ANALYTIC_ID, scope)
        return

    if _ensure_current_turn_scheduler(ctx, services, scope, turn):
        ctx.invalidate_export_snapshot(ANALYTIC_ID, scope)


def _ensure_current_turn_scheduler(
    ctx: AnalyticQueryContext,
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo,
) -> bool:
    player_id = scope.player_id
    assert player_id is not None
    stream_scope = scores_inference_stream_scope(scope)
    if services.scheduler.row_run_for_player(stream_scope, player_id) is not None:
        return False

    controller = controller_for_scope(stream_scope)
    stream_token = controller.stream_token if controller is not None else None

    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    if score is None:
        return False

    resolved_mask = services.resolve_hull_catalog_mask(turn, player_id)
    schedule_inference_row(
        services.scheduler,
        score=score,
        turn=turn,
        player_id=player_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        load_scoreboard_turn=ctx.load_turn,
        resolved_mask=resolved_mask,
        stream_token=stream_token,
    )
    return True


def materialize_scores_export_tree(ctx: AnalyticQueryContext, scope: ExportScope) -> dict[str, Any]:
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        raise ValidationError(f"Turn {scope.turn} is not stored")

    services, resolved = _scores_resolved(ctx, scope, turn=turn)
    return build_scores_export_materialized_tree(
        resolved,
        scope,
        services=services,
        turn=turn,
    )


EXPORT_CATALOG = AnalyticExportCatalog(
    analytic_id=ANALYTIC_ID,
    value_schema=EXPORT_VALUE_SCHEMA,
    path_prefix_scope_rules=PATH_PREFIX_SCOPE_RULES,
    ordering_semantics=ORDERING_SEMANTICS,
    ensure_dependencies=ENSURE_DEPENDENCIES,
    ensure_export=ensure_scores_export,
    materialize_export_tree=materialize_scores_export_tree,
    is_persisted=is_scores_export_persisted,
    is_ensure_satisfied=is_scores_export_ensure_satisfied,
)
