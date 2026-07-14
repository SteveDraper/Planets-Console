"""Export catalog for the scores turn analytic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.meta_wire import build_export_meta_branch
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_stream_rows import (
    ImmediateRowAdmission,
    immediate_row_inference_events,
    schedule_inference_row,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    resolve_prior_turn_fleet_torp_overlay,
)
from api.analytics.scores.export_precedence import (
    ScoresExportResolutionContext,
    ScoresExportResolved,
    is_scores_export_authoritatively_persisted,
    is_scores_export_ensure_satisfied_from_snapshot,
    is_scores_export_turn_evidence_closed_from_snapshot,
    resolve_scores_export,
)
from api.analytics.scores.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.scores.export_services import ScoresExportContext, resolve_scores_services
from api.analytics.scores.export_snapshot import (
    gather_scores_ensure_probe_snapshot,
    gather_scores_inference_snapshot,
    scores_inference_stream_scope,
)
from api.analytics.scores_assets import ANALYTIC_ID
from api.errors import ValidationError
from api.models.game import TurnInfo
from api.models.player import Score
from api.serialization.inference_row_persistence import PersistedInferenceRow

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

ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = (
    EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same"),
)


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
    stream_token = services.resolve_stream_token(stream_scope)
    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    resolved_mask = services.resolve_hull_catalog_mask(turn, player_id)
    return ScoresRowEnsureInputs(
        player_id=player_id,
        score=score,
        resolved_mask=resolved_mask,
        stream_scope=stream_scope,
        stream_token=stream_token,
    )


def _scores_resolution_context(
    ctx: AnalyticQueryContext,
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo,
) -> ScoresExportResolutionContext:
    assert scope.player_id is not None

    def get_persisted_row(scoreboard_turn: int, player_id: int) -> PersistedInferenceRow | None:
        if services.persistence is None:
            return None
        return services.persistence.get_row(
            scope.game_id,
            scope.perspective,
            scoreboard_turn,
            player_id,
        )

    score = next((row for row in turn.scores if row.ownerid == scope.player_id), None)
    return ScoresExportResolutionContext(
        scoreboard_turn=scope.turn,
        turn=turn,
        player_id=scope.player_id,
        load_scoreboard_turn=ctx.load_turn,
        get_persisted_row=get_persisted_row,
        player_score=score,
    )


def _scores_resolved(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    turn: TurnInfo | None = None,
) -> tuple[ScoresExportContext, ScoresExportResolved]:
    services = resolve_scores_services(ctx)
    resolved_turn = turn if turn is not None else ctx.load_turn(scope.turn)
    if resolved_turn is None:
        raise ValidationError(f"Turn {scope.turn} is not stored")

    def gather() -> ScoresExportResolved:
        snapshot = gather_scores_inference_snapshot(ctx, services, scope, resolved_turn)
        resolution_context = _scores_resolution_context(ctx, services, scope, resolved_turn)
        return resolve_scores_export(
            snapshot,
            resolution_context=resolution_context,
        )

    resolved = ctx.export_snapshot_for(ANALYTIC_ID, scope, gather)
    return services, resolved


def held_scores_for_scope(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    turn: TurnInfo | None = None,
) -> ScoresExportResolved:
    """Resolve held inference solutions for one player scope via the scores export pipeline."""
    _, resolved = _scores_resolved(ctx, scope, turn=turn)
    return resolved


def is_scores_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if scope.player_id is None:
        return False

    _services, resolved = _scores_resolved(ctx, scope)
    return is_scores_export_authoritatively_persisted(resolved)


def is_scores_export_ensure_satisfied(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    """Probe/ensure hook: classify gathered state only; no inference or payload build."""
    if scope.player_id is None:
        return True
    if scope.turn <= 1:
        # Game-start neutral priors; fleet@0 is not a valid ensure target.
        return True

    services = resolve_scores_services(ctx)
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return True

    snapshot = gather_scores_ensure_probe_snapshot(
        ctx,
        services,
        scope,
        turn,
    )
    resolution_context = _scores_resolution_context(ctx, services, scope, turn)
    return is_scores_export_ensure_satisfied_from_snapshot(
        snapshot,
        resolution_context=resolution_context,
    )


def is_scores_export_turn_evidence_closed(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    """True when scores@N is terminal for fleet ``turnEvidenceAtN``.

    Unlike ``is_scores_export_ensure_satisfied``, an in-progress scheduler ``RowRun``
    does not count -- fleet must wait for persisted or otherwise terminal scores.
    """
    if scope.player_id is None:
        return True
    if scope.turn <= 1:
        return True

    services = resolve_scores_services(ctx)
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return True

    snapshot = gather_scores_ensure_probe_snapshot(
        ctx,
        services,
        scope,
        turn,
    )
    resolution_context = _scores_resolution_context(ctx, services, scope, turn)
    return is_scores_export_turn_evidence_closed_from_snapshot(
        snapshot,
        resolution_context=resolution_context,
    )


def ensure_scores_export(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    """Admit scores work for one scope without running CP-SAT on this thread.

    Ambient and historical turns share the same path. Satisfaction is probe-aligned
    (persistence, scheduler, ensure-ephemeral) so cheap terminals from
    ``immediate_row_inference_events`` are stashed for probe; real solve work
    schedules a ``RowRun`` for orchestrator ``tier_solve``.
    """
    if scope.player_id is None:
        return True
    if scope.turn <= 1:
        # Game-start neutral priors; fleet@0 is not a valid ensure target.
        return True

    services = resolve_scores_services(ctx)
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return True

    snapshot = gather_scores_ensure_probe_snapshot(ctx, services, scope, turn)
    resolution_context = _scores_resolution_context(ctx, services, scope, turn)
    if is_scores_export_ensure_satisfied_from_snapshot(
        snapshot,
        resolution_context=resolution_context,
    ):
        return True

    mutated = _ensure_admit_inference_row(ctx, services, scope, turn)
    if not mutated:
        return is_scores_export_ensure_satisfied_from_snapshot(
            gather_scores_ensure_probe_snapshot(ctx, services, scope, turn),
            resolution_context=resolution_context,
        )

    ctx.invalidate_export_scope_cache(ANALYTIC_ID, scope)
    _, resolved = _scores_resolved(ctx, scope, turn=turn)
    return resolved.decision.is_ensure_satisfied


def _ensure_admit_inference_row(
    ctx: AnalyticQueryContext,
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo,
) -> bool:
    """Admit cheap terminals via ephemeral events, else schedule a RowRun for CP-SAT."""
    player_id = scope.player_id
    if player_id is None:
        return False

    immediate = immediate_row_inference_events(
        turn,
        player_id,
        load_scoreboard_turn=ctx.load_turn,
    )
    if immediate is not None:
        ctx.record_ensure_ephemeral(
            ANALYTIC_ID,
            scope,
            ImmediateRowAdmission(events=immediate),
        )
        return True

    inputs = _scores_row_ensure_inputs(services, scope, turn)
    if inputs is None:
        return False
    score = inputs.score
    # immediate_row_inference_events admits missing scoreboard rows above.
    assert score is not None
    if services.scheduler.row_run_for_player(inputs.stream_scope, inputs.player_id) is not None:
        return False

    fleet_resolution = resolve_prior_turn_fleet_torp_overlay(
        turn=turn,
        player_id=inputs.player_id,
        load_turn=ctx.load_turn,
        query_context=ctx,
    )
    schedule_inference_row(
        services.scheduler,
        score=score,
        turn=turn,
        player_id=inputs.player_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        load_scoreboard_turn=ctx.load_turn,
        resolved_mask=inputs.resolved_mask,
        fleet_torp_overlay=fleet_resolution.overlay,
        fleet_torp_input_status=fleet_resolution.input_status,
        prior_fleet_max_tech_by_axis=fleet_resolution.prior_fleet_max_tech_for_admission(),
        export_services=ctx.export_services,
        stream_token=inputs.stream_token,
    )
    return True


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
    payload = resolved.payload
    tree: dict[str, Any] = {
        "meta": build_export_meta_branch(
            host_turn=scope.turn,
            search_status=resolved.decision.search_status,
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
