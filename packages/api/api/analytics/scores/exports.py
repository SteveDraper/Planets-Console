"""Export catalog for the scores turn analytic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api.analytics.export_types import ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.military_score_inference.hull_catalog_mask import resolve_hull_catalog_mask
from api.analytics.military_score_inference.inference_scheduler import get_inference_row_scheduler
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
    export_meta_branch,
    held_solution_count,
    hull_catalog_mask_branch,
    is_persistable_inference_status,
    is_scores_export_inference_satisfied,
    ranked_solutions_from_wire,
    resolve_search_status,
    solutions_diagnostics_from_wire_complete_event,
    solutions_from_domain,
)
from api.analytics.scores.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.scores_assets import ANALYTIC_ID
from api.serialization.inference_row_persistence import (
    PersistedInferenceRow,
    persisted_inference_row_from_wire_complete,
)

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext

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


def _scores_services(ctx: AnalyticQueryContext):
    return ctx.scores_export


def _persistence(ctx: AnalyticQueryContext):
    services = _scores_services(ctx)
    return None if services is None else services.persistence


def _scheduler(ctx: AnalyticQueryContext):
    services = _scores_services(ctx)
    if services is not None and services.scheduler is not None:
        return services.scheduler
    return get_inference_row_scheduler()


def _resolve_mask(ctx: AnalyticQueryContext, turn, player_id: int):
    services = _scores_services(ctx)
    if services is not None and services.resolve_hull_catalog_mask is not None:
        return services.resolve_hull_catalog_mask(turn, player_id)
    return resolve_hull_catalog_mask(turn, player_id, user_enabled_hull_ids=None)


def _stream_scope(scope: ExportScope) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
    )


def _load_persisted_row(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> PersistedInferenceRow | None:
    persistence = _persistence(ctx)
    if persistence is None or scope.player_id is None:
        return None
    return persistence.get_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        scope.player_id,
    )


def _row_admission(ctx: AnalyticQueryContext, scope: ExportScope, turn):
    if scope.player_id is None:
        return None
    return resolve_row_stream_admission(
        turn,
        scope.player_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
        load_scoreboard_turn=ctx.load_turn,
        persistence=_persistence(ctx),
    )


def _scheduler_row_run(ctx: AnalyticQueryContext, scope: ExportScope):
    if scope.player_id is None:
        return None
    return _scheduler(ctx).row_run_for_player(_stream_scope(scope), scope.player_id)


def is_scores_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if scope.player_id is None:
        return False

    persisted_row = _load_persisted_row(ctx, scope)
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return is_scores_export_inference_satisfied(
            persisted_row=persisted_row,
            admission=None,
            scheduler_run=None,
            globally_paused=False,
            scope_matches_active_stream=False,
        )

    admission = _row_admission(ctx, scope, turn)
    scheduler_run = _scheduler_row_run(ctx, scope)
    stream_scope = _stream_scope(scope)
    scheduler = _scheduler(ctx)
    pause_status = scheduler.global_pause_status(stream_scope)
    globally_paused = bool(pause_status.get("paused"))
    scope_matches_active_stream = scheduler.active_scope_matches(stream_scope)

    return is_scores_export_inference_satisfied(
        persisted_row=persisted_row,
        admission=admission,
        scheduler_run=scheduler_run,
        globally_paused=globally_paused,
        scope_matches_active_stream=scope_matches_active_stream,
    )


def ensure_scores_export(ctx: AnalyticQueryContext, scope: ExportScope) -> None:
    if scope.player_id is None:
        return

    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return

    if _load_persisted_row(ctx, scope) is not None:
        return

    admission = _row_admission(ctx, scope, turn)
    if isinstance(admission, (ImmediateRowAdmission, CachedCompleteRowAdmission)):
        return

    if scope.turn < ctx.ambient_turn:
        _ensure_prior_turn_sync(ctx, scope, turn)
        return

    _ensure_current_turn_scheduler(ctx, scope, turn)


def _ensure_prior_turn_sync(ctx: AnalyticQueryContext, scope: ExportScope, turn) -> None:
    from api.analytics.scores import get_scores_row_inference

    player_id = scope.player_id
    assert player_id is not None
    resolved_mask = _resolve_mask(ctx, turn, player_id)
    inference = get_scores_row_inference(
        turn,
        player_id,
        load_scoreboard_turn=ctx.load_turn,
        resolved_mask=resolved_mask,
    )
    persistence = _persistence(ctx)
    if persistence is None:
        return
    status = str(inference.get("status", ""))
    if not is_persistable_inference_status(status):
        return
    wire_solutions = inference.get("solutions")
    wire_event = {
        "type": "complete",
        "status": status,
        "summary": str(inference.get("summary", "")),
        "solutionCount": int(inference.get("solutionCount", 0)),
        "isComplete": bool(inference.get("isComplete", True)),
        "solutions": wire_solutions if isinstance(wire_solutions, list) else [],
        "diagnostics": inference.get("diagnostics")
        if isinstance(inference.get("diagnostics"), dict)
        else None,
    }
    row = persisted_inference_row_from_wire_complete(wire_event)
    persistence.put_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        player_id,
        row,
    )


def _ensure_current_turn_scheduler(ctx: AnalyticQueryContext, scope: ExportScope, turn) -> None:
    player_id = scope.player_id
    assert player_id is not None
    scheduler = _scheduler(ctx)
    stream_scope = _stream_scope(scope)
    if scheduler.row_run_for_player(stream_scope, player_id) is not None:
        return

    controller = controller_for_scope(stream_scope)
    stream_token = controller.stream_token if controller is not None else None

    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    if score is None:
        return

    resolved_mask = _resolve_mask(ctx, turn, player_id)
    schedule_inference_row(
        scheduler,
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
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return {
            "meta": export_meta_branch(
                search_status="not_started",
                host_turn=scope.turn,
            ),
            "solutions": [],
        }

    persisted_row = _load_persisted_row(ctx, scope)
    admission = _row_admission(ctx, scope, turn)
    scheduler_run = _scheduler_row_run(ctx, scope)
    stream_scope = _stream_scope(scope)
    scheduler = _scheduler(ctx)
    pause_status = scheduler.global_pause_status(stream_scope)
    globally_paused = bool(pause_status.get("paused"))
    scope_matches_active_stream = scheduler.active_scope_matches(stream_scope)

    search_status = resolve_search_status(
        persisted_row=persisted_row,
        admission=admission,
        scheduler_run=scheduler_run,
        globally_paused=globally_paused,
        scope_matches_active_stream=scope_matches_active_stream,
    )

    solutions: list[dict[str, object]] = []
    diagnostics: dict[str, object] | None = None

    if persisted_row is not None:
        solutions = ranked_solutions_from_wire(persisted_row.solutions)
        diagnostics = persisted_row.diagnostics
        solutions_held = persisted_row.solution_count
    elif isinstance(admission, ImmediateRowAdmission) and admission.events:
        solutions, diagnostics, solutions_held = solutions_diagnostics_from_wire_complete_event(
            admission.events[-1]
        )
    elif isinstance(admission, CachedCompleteRowAdmission) and admission.event is not None:
        solutions, diagnostics, solutions_held = solutions_diagnostics_from_wire_complete_event(
            admission.event
        )
    elif scheduler_run is not None and scheduler_run.ladder_state is not None:
        ladder_state = scheduler_run.ladder_state
        merged = ladder_state.merged_solutions
        solutions = solutions_from_domain(
            merged,
            observation=scheduler_run.session.observation,
            catalog=ladder_state.catalog,
        )
        solutions_held = len(merged)
    else:
        solutions_held = held_solution_count(
            persisted_row=persisted_row,
            scheduler_run=scheduler_run,
        )

    tree: dict[str, Any] = {
        "meta": export_meta_branch(
            search_status=search_status,
            host_turn=scope.turn,
            solutions_held=solutions_held,
        ),
        "solutions": solutions,
    }
    if diagnostics is not None:
        tree["diagnostics"] = diagnostics

    if scope.player_id is not None:
        resolved_mask = _resolve_mask(ctx, turn, scope.player_id)
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
