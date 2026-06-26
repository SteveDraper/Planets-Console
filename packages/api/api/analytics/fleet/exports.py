"""Export catalog for the fleet turn analytic."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.fleet.compute_services import resolve_fleet_services
from api.analytics.fleet.serialization import fleet_acquisition_ledger_to_json
from api.analytics.fleet.types import FleetAcquisitionLedger, FleetTurnSnapshot
from api.analytics.scores.export_precedence import SearchStatus
from api.analytics.scores.exports import held_scores_for_scope
from api.errors import ValidationError
from api.models.game import TurnInfo

PATH_PREFIX_SCOPE_RULES = (
    PathPrefixScopeRule(prefix="$.players", requires=("player_id",)),
    PathPrefixScopeRule(prefix="$.meta.searchStatus", requires=("player_id",)),
    PathPrefixScopeRule(prefix="$.meta.solutionsHeld", requires=("player_id",)),
)

ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = (
    EnsureDependency(analytic_id="scores", turn_delta=0, player_id="same"),
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
        return get_or_materialize_fleet_snapshot(
            services.persistence,
            services.game_id,
            services.perspective,
            resolved_turn,
            load_turn=services.load_turn,
            inference_materialization=services.inference_materialization,
        )

    return ctx.export_snapshot_for(ANALYTIC_ID, scope, gather)


def is_fleet_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    services = resolve_fleet_services(ctx)
    return services.persistence.has_snapshot(
        services.game_id,
        services.perspective,
        scope.turn,
    )


def is_fleet_export_ensure_satisfied(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    """Probe/ensure hook: fleet export is satisfied when the turn snapshot is stored."""
    return is_fleet_export_persisted(ctx, scope)


def ensure_fleet_export(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if is_fleet_export_persisted(ctx, scope):
        return True

    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return True

    _fleet_snapshot_for_scope(ctx, scope, turn=turn)
    ctx.invalidate_export_scope_cache(ANALYTIC_ID, scope)
    return is_fleet_export_persisted(ctx, scope)


def _scores_search_status_for_scope(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    turn: TurnInfo,
) -> tuple[SearchStatus, int]:
    if scope.player_id is None:
        return "not_started", 0

    resolved = held_scores_for_scope(ctx, scope, turn=turn)
    return resolved.decision.search_status, resolved.payload.solutions_held


def _export_meta_branch(
    *,
    search_status: SearchStatus | None,
    host_turn: int,
    solutions_held: int = 0,
) -> dict[str, object]:
    meta: dict[str, object] = {"hostTurn": host_turn}
    if search_status is not None:
        meta["searchStatus"] = search_status
    if solutions_held > 0:
        meta["solutionsHeld"] = solutions_held
    return meta


def _players_for_scope(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
) -> list[FleetAcquisitionLedger]:
    if scope.player_id is None:
        return list(snapshot.players)
    return [ledger for ledger in snapshot.players if ledger.player_id == scope.player_id]


def build_fleet_export_materialized_tree(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
    *,
    search_status: SearchStatus | None,
    solutions_held: int,
) -> dict[str, Any]:
    """Materialize the full fleet export value tree for one resolved snapshot."""
    return {
        "meta": _export_meta_branch(
            search_status=search_status,
            host_turn=scope.turn,
            solutions_held=solutions_held,
        ),
        "players": [
            fleet_acquisition_ledger_to_json(player_ledger)
            for player_ledger in _players_for_scope(snapshot, scope)
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

    return build_fleet_export_materialized_tree(
        snapshot,
        scope,
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
