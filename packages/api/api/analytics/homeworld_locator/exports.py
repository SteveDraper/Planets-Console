"""Export catalog for the homeworld locator turn analytic."""

from __future__ import annotations

from typing import Any, NoReturn

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_turn_fill import ChainFillReason, DependencyChainFillError
from api.analytics.export_types import (
    EnsureDependency,
    ExportScope,
    PathPrefixScopeRule,
)
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.meta_wire import build_export_meta_branch
from api.analytics.homeworld_locator.baseline_ensure import (
    ensure_homeworld_baseline,
    needs_baseline_recompute,
)
from api.analytics.homeworld_locator.compute_services import resolve_homeworld_services
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.evidence_ensure import (
    ensure_homeworld_evidence_refined,
    evidence_refined_through_shell,
)
from api.analytics.homeworld_locator.evidence_refine_report import build_ensure_failure_report
from api.analytics.homeworld_locator.evidence_refine_timing_history import (
    record_ensure_failure_report,
)
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

# Baseline floor at turn 1 (or degraded earliest) plus linear self-chain for
# shell-turn evidence refine. Ship ages are read from on-disk fleet ledgers at
# each refine turn; the locator does not ensure fleet.
ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = (
    EnsureDependency(analytic_id=ANALYTIC_ID, turn_delta=-1, player_id="same"),
)

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
        "shellAggregate": {
            "type": "object",
            "description": "Evidence aggregate refined through the shell turn.",
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
    if needs_baseline_recompute(services, settings_fingerprint=fingerprint):
        return False
    state = services.persistence.get_game_state(services.game_id)
    if state is None:
        return False
    return evidence_refined_through_shell(
        services,
        baseline_turn=state.baseline_turn,
        shell_turn=scope.turn,
    )


def is_homeworld_export_persisted(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    return is_homeworld_export_ensure_satisfied(ctx, scope)


def _record_ensure_failure_and_raise(
    scope: ExportScope,
    *,
    reason: ChainFillReason,
    message: str,
    missing_turn: int | None,
) -> NoReturn:
    """Record homeworld ensure-failure diagnostics, then surface the failure to the caller."""
    record_ensure_failure_report(
        build_ensure_failure_report(
            game_id=scope.game_id,
            perspective=scope.perspective,
            shell_turn=scope.turn,
            reason=reason,
            message=message,
            missing_turn=missing_turn,
        )
    )
    raise ValidationError(message)


def ensure_homeworld_export(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    """Bring homeworld export scope to satisfaction via orchestrator submit+wait.

    The orchestrator's root plan fills missing dependency-chain turns. A
    ``DependencyChainFillError`` from it is recorded as an ensure failure for
    this shell turn and re-raised in homeworld wording.
    """
    if is_homeworld_export_ensure_satisfied(ctx, scope):
        return True

    turn = ctx.load_turn(scope.turn)
    if turn is None:
        _record_ensure_failure_and_raise(
            scope,
            reason="turn_not_stored",
            message=(
                f"homeworld locator cannot refine turn {scope.turn}: "
                f"turn {scope.turn} is not stored"
            ),
            missing_turn=scope.turn,
        )
    if not is_homeworld_locator_available(turn.settings):
        return True

    from api.compute.export_ensure import ensure_export_scope_via_orchestrator

    try:
        satisfied = ensure_export_scope_via_orchestrator(ctx, ANALYTIC_ID, scope)
    except DependencyChainFillError as error:
        _record_ensure_failure_and_raise(
            scope,
            reason=error.reason,
            message=f"homeworld locator cannot refine turn {scope.turn}: {error.detail}",
            missing_turn=error.missing_turn,
        )
    ctx.invalidate_export_scope_cache(ANALYTIC_ID, scope)
    return satisfied


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
    result = ensure_homeworld_baseline(ctx, shell_turn=turn)
    # Single-step refine at shell; prior turns already ensured via DAG unwind.
    shell_aggregate = ensure_homeworld_evidence_refined(
        services,
        shell_turn=turn,
        game_state_baseline_turn=result.game_state.baseline_turn,
    )
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
        "shellAggregate": homeworld_evidence_aggregate_to_json(shell_aggregate),
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
