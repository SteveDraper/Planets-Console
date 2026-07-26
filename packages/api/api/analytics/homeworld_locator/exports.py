"""Export catalog for the homeworld locator turn analytic."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope, PathPrefixScopeRule
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.meta_wire import build_export_meta_branch
from api.analytics.homeworld_locator.baseline_ensure import (
    ensure_homeworld_baseline,
    needs_baseline_recompute,
)
from api.analytics.homeworld_locator.compute_services import resolve_homeworld_services
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.serialization import (
    homeworld_candidate_record_to_json,
    homeworld_evidence_aggregate_to_json,
    homeworld_locator_game_state_to_json,
)
from api.concepts.homeworld_layout import (
    homeworld_settings_fingerprint,
    is_homeworld_locator_available,
)
from api.errors import ValidationError

PATH_PREFIX_SCOPE_RULES: tuple[PathPrefixScopeRule, ...] = ()

# Phase 2 (#34) is baseline-only and game-global: no prior-turn self-chain.
# A turn_delta=-1 edge would require every intermediate turn to be stored
# before baseline upgrade (degraded→T1) can run. #36 refine-through-T adds
# the self-chain when shell-turn evidence copy-forward is in scope.
ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = ()

EXPORT_VALUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Homeworld locator export tree: baseline metadata, candidate list, and floor "
        "evidence aggregate (#34 baseline-only; #36 refines evidence through shell turn)."
    ),
    "properties": {
        "meta": {
            "type": "object",
            "description": "Export meta branch (host turn).",
            "properties": {
                "hostTurn": {
                    "type": "integer",
                    "description": "Shell/host turn for this export scope.",
                },
            },
        },
        "baseline": {
            "type": "object",
            "description": "Baseline turn identity and degraded flag.",
            "properties": {
                "baselineTurn": {
                    "type": "integer",
                    "description": "Turn number used as the homeworld inference baseline.",
                },
                "baselineDegraded": {
                    "type": "boolean",
                    "description": "True when baseline used a turn other than turn 1.",
                },
            },
        },
        "candidates": {
            "type": "array",
            "description": "Homeworld candidate records from game-global state.",
        },
        "floorAggregate": {
            "type": "object",
            "description": "Floor evidence aggregate persisted at the baseline turn.",
        },
    },
}


def is_homeworld_export_ensure_satisfied(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    """Satisfied when inactive, or when :func:`needs_baseline_recompute` is False.

    Shares the same baseline quality policy as SPA ensure (missing floor,
    settings fingerprint mismatch, degraded baseline after turn 1 appears).
    """
    services = resolve_homeworld_services(ctx)
    turn = ctx.load_turn(scope.turn)
    if turn is not None and not is_homeworld_locator_available(turn.settings):
        return True
    if turn is None:
        # No scope settings turn to fingerprint: still apply floor / degraded+T1
        # checks by using the durable fingerprint (fingerprint axis is a no-op).
        state = services.persistence.get_game_state(services.game_id)
        if state is None:
            return False
        fingerprint = state.settings_fingerprint
    else:
        fingerprint = homeworld_settings_fingerprint(turn.settings)
    return not needs_baseline_recompute(services, settings_fingerprint=fingerprint)


def is_homeworld_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    return is_homeworld_export_ensure_satisfied(ctx, scope)


def ensure_homeworld_export(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    if is_homeworld_export_ensure_satisfied(ctx, scope):
        return True

    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return True
    if not is_homeworld_locator_available(turn.settings):
        return True

    if ctx.ensure_declared_dependencies(ANALYTIC_ID, scope) is not None:
        return is_homeworld_export_ensure_satisfied(ctx, scope)

    services = resolve_homeworld_services(ctx)
    ensure_homeworld_baseline(services, shell_turn=turn)
    ctx.invalidate_export_scope_cache(ANALYTIC_ID, scope)
    return is_homeworld_export_ensure_satisfied(ctx, scope)


def materialize_homeworld_export_tree(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> dict[str, Any]:
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        raise ValidationError(f"Turn {scope.turn} is not stored")
    if not is_homeworld_locator_available(turn.settings):
        return {
            "meta": build_export_meta_branch(host_turn=scope.turn),
            "baseline": None,
            "candidates": [],
            "floorAggregate": None,
            "available": False,
        }

    services = resolve_homeworld_services(ctx)
    result = ensure_homeworld_baseline(services, shell_turn=turn)
    return {
        "meta": build_export_meta_branch(host_turn=scope.turn),
        "baseline": {
            "baselineTurn": result.game_state.baseline_turn,
            "baselineDegraded": result.game_state.baseline_degraded,
        },
        "candidates": [
            homeworld_candidate_record_to_json(row) for row in result.game_state.candidates
        ],
        "floorAggregate": homeworld_evidence_aggregate_to_json(result.floor_aggregate),
        "gameState": homeworld_locator_game_state_to_json(result.game_state),
        "available": True,
    }


EXPORT_CATALOG = AnalyticExportCatalog(
    analytic_id=ANALYTIC_ID,
    value_schema=EXPORT_VALUE_SCHEMA,
    path_prefix_scope_rules=PATH_PREFIX_SCOPE_RULES,
    ensure_dependencies=ENSURE_DEPENDENCIES,
    ensure_export=ensure_homeworld_export,
    materialize_export_tree=materialize_homeworld_export_tree,
    is_persisted=is_homeworld_export_persisted,
    is_ensure_satisfied=is_homeworld_export_ensure_satisfied,
)
