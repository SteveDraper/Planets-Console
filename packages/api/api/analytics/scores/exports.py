"""Export catalog for the scores turn analytic."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    resolve_row_stream_admission,
    schedule_inference_row,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
)
from api.analytics.scores.export_materialization import (
    ScoresInferenceSnapshot,
    export_meta_branch,
    hull_catalog_mask_branch,
    is_persistable_inference_status,
    is_scores_export_inference_satisfied,
    resolve_scores_export_payload,
)
from api.analytics.scores.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.scores.export_services import ResolvedScoresServices, resolve_scores_services
from api.analytics.scores_assets import ANALYTIC_ID
from api.serialization.inference_row_persistence import (
    PersistedInferenceRow,
    persisted_inference_row_from_wire_complete,
)
from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

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

ENSURE_DEPENDENCIES: tuple = ()


def _stream_scope(scope: ExportScope) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
    )


def _load_persisted_row(
    services: ResolvedScoresServices,
    scope: ExportScope,
) -> PersistedInferenceRow | None:
    if services.persistence is None or scope.player_id is None:
        return None
    return services.persistence.get_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        scope.player_id,
    )


def _row_admission(
    ctx: AnalyticQueryContext,
    services: ResolvedScoresServices,
    scope: ExportScope,
    turn,
):
    if scope.player_id is None:
        return None
    return resolve_row_stream_admission(
        turn,
        scope.player_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
        load_scoreboard_turn=ctx.load_turn,
        persistence=services.persistence,
    )


def _scheduler_row_run(services: ResolvedScoresServices, scope: ExportScope):
    if scope.player_id is None:
        return None
    return services.scheduler.row_run_for_player(_stream_scope(scope), scope.player_id)


def _resolve_scores_inference_snapshot(
    ctx: AnalyticQueryContext,
    services: ResolvedScoresServices,
    scope: ExportScope,
    turn,
) -> ScoresInferenceSnapshot:
    persisted_row = _load_persisted_row(services, scope)
    if turn is None:
        return ScoresInferenceSnapshot(
            persisted_row=persisted_row,
            admission=None,
            scheduler_run=None,
            globally_paused=False,
        )

    stream_scope = _stream_scope(scope)
    pause_status = services.scheduler.global_pause_status(stream_scope)
    return ScoresInferenceSnapshot(
        persisted_row=persisted_row,
        admission=_row_admission(ctx, services, scope, turn),
        scheduler_run=_scheduler_row_run(services, scope),
        globally_paused=bool(pause_status.get("paused")),
    )


def is_scores_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if scope.player_id is None:
        return False

    services = resolve_scores_services(ctx)
    snapshot = _resolve_scores_inference_snapshot(
        ctx, services, scope, ctx.load_turn(scope.turn)
    )
    return is_scores_export_inference_satisfied(
        persisted_row=snapshot.persisted_row,
        admission=snapshot.admission,
        scheduler_run=snapshot.scheduler_run,
        globally_paused=snapshot.globally_paused,
    )


def ensure_scores_export(ctx: AnalyticQueryContext, scope: ExportScope) -> None:
    if scope.player_id is None:
        return

    services = resolve_scores_services(ctx)
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return

    if _load_persisted_row(services, scope) is not None:
        return

    admission = _row_admission(ctx, services, scope, turn)
    if isinstance(admission, (ImmediateRowAdmission, CachedCompleteRowAdmission)):
        return

    if scope.turn < ctx.ambient_turn:
        _ensure_prior_turn_sync(ctx, services, scope, turn)
        return

    _ensure_current_turn_scheduler(ctx, services, scope, turn)


def _ensure_prior_turn_sync(
    ctx: AnalyticQueryContext,
    services: ResolvedScoresServices,
    scope: ExportScope,
    turn,
) -> None:
    from api.analytics.scores import get_scores_row_inference

    player_id = scope.player_id
    assert player_id is not None
    resolved_mask = services.resolve_hull_catalog_mask(turn, player_id)
    inference = get_scores_row_inference(
        turn,
        player_id,
        load_scoreboard_turn=ctx.load_turn,
        resolved_mask=resolved_mask,
    )
    if services.persistence is None:
        return
    status = str(inference.get("status", ""))
    if not is_persistable_inference_status(status):
        return
    wire_event = inference_api_payload_to_wire_complete(inference)
    row = persisted_inference_row_from_wire_complete(wire_event)
    services.persistence.put_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        player_id,
        row,
    )


def _ensure_current_turn_scheduler(
    ctx: AnalyticQueryContext,
    services: ResolvedScoresServices,
    scope: ExportScope,
    turn,
) -> None:
    player_id = scope.player_id
    assert player_id is not None
    stream_scope = _stream_scope(scope)
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
    if turn is None:
        return {
            "meta": export_meta_branch(
                search_status="not_started",
                host_turn=scope.turn,
            ),
            "solutions": [],
        }

    snapshot = _resolve_scores_inference_snapshot(ctx, services, scope, turn)
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
