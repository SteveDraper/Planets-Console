"""Export catalog for the fleet turn analytic."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.meta_wire import build_export_meta_branch
from api.analytics.fleet.chain import (
    get_or_materialize_fleet_ledger_for_player,
    get_or_materialize_fleet_snapshot,
)
from api.analytics.fleet.composition_export import build_fleet_composition_branch
from api.analytics.fleet.compute_services import resolve_fleet_services
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.fleet.export_scope import ledgers_for_scope
from api.analytics.fleet.serialization import fleet_acquisition_ledger_to_json
from api.analytics.fleet.types import FleetTurnSnapshot
from api.analytics.scores.export_precedence import SearchStatus
from api.analytics.scores.exports import held_scores_for_scope
from api.errors import FleetGapFillEpochInvalidated, ValidationError
from api.models.game import TurnInfo

PATH_PREFIX_SCOPE_RULES = (
    PathPrefixScopeRule(prefix="$.players", requires=("player_id",)),
    PathPrefixScopeRule(prefix="$.composition", requires=("player_id",)),
    PathPrefixScopeRule(prefix="$.meta.searchStatus", requires=("player_id",)),
    PathPrefixScopeRule(prefix="$.meta.solutionsHeld", requires=("player_id",)),
)

ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = (
    EnsureDependency(analytic_id="scores", turn_delta=0, player_id="same"),
    EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same"),
)


def _fleet_snapshot_for_scope(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    turn: TurnInfo | None = None,
) -> FleetTurnSnapshot:
    services = resolve_fleet_services(ctx)
    resolved_turn = turn if turn is not None else ctx.load_turn(scope.turn)
    if resolved_turn is None:
        raise ValidationError(f"Turn {scope.turn} is not stored")

    def gather() -> FleetTurnSnapshot:
        if scope.player_id is not None:
            persisted = get_or_materialize_fleet_ledger_for_player(
                services.persistence,
                services.game_id,
                services.perspective,
                scope.player_id,
                resolved_turn,
                load_turn=services.load_turn,
                inference_materialization=services.inference_materialization,
                query_context=ctx,
            )
            return FleetTurnSnapshot(
                analytic_id=ANALYTIC_ID,
                game_id=services.game_id,
                perspective=services.perspective,
                turn=scope.turn,
                players=[persisted.ledger],
            )
        return get_or_materialize_fleet_snapshot(
            services.persistence,
            services.game_id,
            services.perspective,
            resolved_turn,
            load_turn=services.load_turn,
            inference_materialization=services.inference_materialization,
            query_context=ctx,
        )

    return ctx.export_snapshot_for(ANALYTIC_ID, scope, gather)


def is_fleet_export_ensure_satisfied(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    """Probe/ensure hook: final only when per-player provenance is (true, true)."""
    if scope.player_id is None:
        return True

    services = resolve_fleet_services(ctx)
    if ctx.load_turn(scope.turn) is None:
        return True

    return services.persistence.has_final_ledger(
        services.game_id,
        services.perspective,
        scope.turn,
        scope.player_id,
    )


def is_fleet_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if scope.player_id is None:
        return False
    return is_fleet_export_ensure_satisfied(ctx, scope)


def ensure_fleet_export(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if is_fleet_export_ensure_satisfied(ctx, scope):
        return True

    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return True

    if ctx.ensure_declared_dependencies(ANALYTIC_ID, scope) is not None:
        return is_fleet_export_ensure_satisfied(ctx, scope)

    try:
        _fleet_snapshot_for_scope(ctx, scope, turn=turn)
    except FleetGapFillEpochInvalidated:
        # Mid-chain invalidation: leave ensure unsatisfied so orchestrator /
        # stream adapters re-queue after the epoch advances or scores evidence closes.
        ctx.invalidate_export_scope_cache(ANALYTIC_ID, scope)
        return is_fleet_export_ensure_satisfied(ctx, scope)
    ctx.invalidate_export_scope_cache(ANALYTIC_ID, scope)
    return is_fleet_export_ensure_satisfied(ctx, scope)


def _scores_search_status_for_scope(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    turn: TurnInfo,
) -> tuple[SearchStatus, int]:
    resolved = held_scores_for_scope(ctx, scope, turn=turn)
    return resolved.decision.search_status, resolved.payload.solutions_held


def _build_fleet_export_materialized_tree(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
    *,
    turn: TurnInfo,
    search_status: SearchStatus | None,
    solutions_held: int,
) -> dict[str, Any]:
    return {
        "meta": build_export_meta_branch(
            host_turn=scope.turn,
            search_status=search_status,
            solutions_held=solutions_held,
        ),
        "composition": build_fleet_composition_branch(snapshot, scope, turn=turn),
        "players": [
            fleet_acquisition_ledger_to_json(player_ledger)
            for player_ledger in ledgers_for_scope(snapshot, scope)
        ],
    }


def materialize_fleet_export_tree(ctx: AnalyticQueryContext, scope: ExportScope) -> dict[str, Any]:
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        raise ValidationError(f"Turn {scope.turn} is not stored")

    snapshot = _fleet_snapshot_for_scope(ctx, scope, turn=turn)
    search_status: SearchStatus | None
    solutions_held: int
    if scope.player_id is None:
        search_status = None
        solutions_held = 0
    else:
        search_status, solutions_held = _scores_search_status_for_scope(
            ctx,
            scope,
            turn=turn,
        )

    return _build_fleet_export_materialized_tree(
        snapshot,
        scope,
        turn=turn,
        search_status=search_status,
        solutions_held=solutions_held,
    )


EXPORT_CATALOG = AnalyticExportCatalog(
    analytic_id=ANALYTIC_ID,
    value_schema=EXPORT_VALUE_SCHEMA,
    path_prefix_scope_rules=PATH_PREFIX_SCOPE_RULES,
    ensure_dependencies=ENSURE_DEPENDENCIES,
    ensure_export=ensure_fleet_export,
    materialize_export_tree=materialize_fleet_export_tree,
    is_persisted=is_fleet_export_persisted,
    is_ensure_satisfied=is_fleet_export_ensure_satisfied,
)
