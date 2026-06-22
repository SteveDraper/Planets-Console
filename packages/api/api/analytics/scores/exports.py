"""Export catalog for the scores turn analytic."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_stream_rows import schedule_inference_row
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
)
from api.analytics.scores.export_precedence import (
    ScoresExportResolved,
    SearchStatus,
    is_persistable_inference_status,
    is_scores_export_authoritatively_persisted,
    is_scores_inference_ensure_satisfied,
    resolve_scores_export,
    resolve_scores_export_payload,
)
from api.analytics.scores.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.scores.export_services import ScoresExportContext, resolve_scores_services
from api.analytics.scores.export_snapshot import (
    gather_scores_inference_snapshot,
    scores_inference_stream_scope,
)
from api.analytics.scores.inference import get_scores_row_inference
from api.analytics.scores_assets import ANALYTIC_ID
from api.errors import ValidationError
from api.models.game import TurnInfo
from api.models.player import Score
from api.serialization.inference_row_persistence import persisted_inference_row_from_wire_complete
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

ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = ()


@dataclass(frozen=True)
class ScoresRowEnsureInputs:
    """Shared row-level inputs for scores export ensure strategies."""

    player_id: int
    score: Score | None
    resolved_mask: ResolvedHullCatalogMask | None
    stream_scope: InferenceStreamScope
    stream_token: str | None


def _scores_row_ensure_inputs(
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo,
) -> ScoresRowEnsureInputs | None:
    player_id = scope.player_id
    if player_id is None:
        return None

    stream_scope = scores_inference_stream_scope(scope)
    controller = controller_for_scope(stream_scope)
    stream_token = controller.stream_token if controller is not None else None
    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    resolved_mask = services.resolve_hull_catalog_mask(turn, player_id)
    return ScoresRowEnsureInputs(
        player_id=player_id,
        score=score,
        resolved_mask=resolved_mask,
        stream_scope=stream_scope,
        stream_token=stream_token,
    )


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


def _sync_persist_empty_branch(
    resolved: ScoresExportResolved,
    *,
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo,
    load_scoreboard_turn: Callable[[int], TurnInfo | None],
) -> bool:
    """Persist sync inference when precedence is empty (prior-turn ensure path)."""
    if not resolved.decision.needs_ensure_work:
        return False
    if services.persistence is None:
        return False

    inputs = _scores_row_ensure_inputs(services, scope, turn)
    if inputs is None:
        return False

    inference = get_scores_row_inference(
        turn,
        inputs.player_id,
        load_scoreboard_turn=load_scoreboard_turn,
        resolved_mask=inputs.resolved_mask,
    )
    status = str(inference.get("status", ""))
    if not is_persistable_inference_status(status):
        return False
    wire_event = inference_api_payload_to_wire_complete(inference)
    row = persisted_inference_row_from_wire_complete(wire_event)
    services.persistence.put_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        inputs.player_id,
        row,
    )
    return True


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
        if _sync_persist_empty_branch(
            resolved,
            services=services,
            scope=scope,
            turn=turn,
            load_scoreboard_turn=ctx.load_turn,
        ):
            ctx.invalidate_export_scope_cache(ANALYTIC_ID, scope)
        return

    if _ensure_current_turn_scheduler(ctx, services, scope, turn):
        ctx.invalidate_export_scope_cache(ANALYTIC_ID, scope)


def _ensure_current_turn_scheduler(
    ctx: AnalyticQueryContext,
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo,
) -> bool:
    inputs = _scores_row_ensure_inputs(services, scope, turn)
    if inputs is None or inputs.score is None:
        return False
    if services.scheduler.row_run_for_player(inputs.stream_scope, inputs.player_id) is not None:
        return False

    schedule_inference_row(
        services.scheduler,
        score=inputs.score,
        turn=turn,
        player_id=inputs.player_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        load_scoreboard_turn=ctx.load_turn,
        resolved_mask=inputs.resolved_mask,
        stream_token=inputs.stream_token,
    )
    return True


def _export_meta_branch(
    *,
    search_status: SearchStatus,
    host_turn: int,
    solutions_held: int = 0,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "searchStatus": search_status,
        "hostTurn": host_turn,
    }
    if solutions_held > 0:
        meta["solutionsHeld"] = solutions_held
    return meta


def _hull_catalog_mask_branch(enabled_hull_ids: frozenset[int] | set[int]) -> dict[str, object]:
    return {"enabledHullIds": sorted(enabled_hull_ids)}


def build_scores_export_materialized_tree(
    resolved: ScoresExportResolved,
    scope: ExportScope,
    *,
    services: ScoresExportContext,
    turn: TurnInfo,
) -> dict[str, Any]:
    """Materialize the full scores export value tree for one resolved snapshot."""
    payload = resolve_scores_export_payload(resolved)
    tree: dict[str, Any] = {
        "meta": _export_meta_branch(
            search_status=resolved.decision.search_status,
            host_turn=scope.turn,
            solutions_held=payload.solutions_held,
        ),
        "solutions": payload.solutions,
    }
    if payload.diagnostics is not None:
        tree["diagnostics"] = payload.diagnostics

    if scope.player_id is not None:
        resolved_mask = services.resolve_hull_catalog_mask(turn, scope.player_id)
        if resolved_mask is not None:
            tree["hullCatalogMask"] = _hull_catalog_mask_branch(
                resolved_mask.effective_enabled_hull_ids
            )

    return tree


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
