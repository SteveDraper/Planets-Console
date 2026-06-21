"""Export catalog for the scores turn analytic."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    schedule_inference_row,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
)
from api.analytics.scores.export_materialization import (
    export_meta_branch,
    gather_scores_inference_snapshot,
    hull_catalog_mask_branch,
    resolve_scores_export_payload,
    scores_inference_stream_scope,
)
from api.analytics.scores.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.scores.export_services import ResolvedScoresServices, resolve_scores_services
from api.analytics.scores.inference_persist import persist_prior_turn_inference_if_persistable
from api.analytics.scores_assets import ANALYTIC_ID

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


def is_scores_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if scope.player_id is None:
        return False

    services = resolve_scores_services(ctx)
    snapshot = gather_scores_inference_snapshot(
        ctx, services, scope, ctx.load_turn(scope.turn)
    )
    return resolve_scores_export_payload(snapshot).search_status == "complete"


def ensure_scores_export(ctx: AnalyticQueryContext, scope: ExportScope) -> None:
    if scope.player_id is None:
        return

    services = resolve_scores_services(ctx)
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return

    snapshot = gather_scores_inference_snapshot(ctx, services, scope, turn)
    if snapshot.persisted_row is not None:
        return

    admission = snapshot.admission
    if isinstance(admission, (ImmediateRowAdmission, CachedCompleteRowAdmission)):
        return

    if scope.turn < ctx.ambient_turn:
        persist_prior_turn_inference_if_persistable(ctx, services, scope, turn)
        return

    _ensure_current_turn_scheduler(ctx, services, scope, turn)


def _ensure_current_turn_scheduler(
    ctx: AnalyticQueryContext,
    services: ResolvedScoresServices,
    scope: ExportScope,
    turn,
) -> None:
    player_id = scope.player_id
    assert player_id is not None
    stream_scope = scores_inference_stream_scope(scope)
    if services.scheduler.row_run_for_player(stream_scope, player_id) is not None:
        return

    controller = controller_for_scope(stream_scope)
    stream_token = controller.stream_token if controller is not None else None

    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    if score is None:
        return

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


def materialize_scores_export_tree(ctx: AnalyticQueryContext, scope: ExportScope) -> dict[str, Any]:
    services = resolve_scores_services(ctx)
    turn = ctx.load_turn(scope.turn)
    assert turn is not None

    snapshot = gather_scores_inference_snapshot(ctx, services, scope, turn)
    payload = resolve_scores_export_payload(snapshot)

    tree: dict[str, Any] = {
        "meta": export_meta_branch(
            search_status=payload.search_status,
            host_turn=scope.turn,
            solutions_held=payload.solutions_held,
        ),
        "solutions": payload.solutions,
    }
    if payload.diagnostics is not None:
        tree["diagnostics"] = payload.diagnostics

    if scope.player_id is not None:
        resolved_mask = services.resolve_hull_catalog_mask(turn, scope.player_id)
        tree["hullCatalogMask"] = hull_catalog_mask_branch(resolved_mask.effective_enabled_hull_ids)

    return tree


EXPORT_CATALOG = AnalyticExportCatalog(
    analytic_id=ANALYTIC_ID,
    value_schema=EXPORT_VALUE_SCHEMA,
    path_prefix_scope_rules=PATH_PREFIX_SCOPE_RULES,
    ordering_semantics=ORDERING_SEMANTICS,
    ensure_dependencies=ENSURE_DEPENDENCIES,
    ensure_export=ensure_scores_export,
    materialize_export_tree=materialize_scores_export_tree,
    is_persisted=is_scores_export_persisted,
)
