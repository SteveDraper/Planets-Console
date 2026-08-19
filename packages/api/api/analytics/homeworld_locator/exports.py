"""Export catalog for the homeworld locator turn analytic."""

from __future__ import annotations

from typing import Any, NoReturn, cast

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_turn_fill import (
    DependencyChainFillError,
    missing_dependency_chain_turns,
    prepare_dependency_chain_turns,
)
from api.analytics.export_types import (
    EnsureDependency,
    ExportScope,
    PathPrefixScopeRule,
    UnavailableReason,
)
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.meta_wire import build_export_meta_branch
from api.analytics.fleet.compute_services import resolve_fleet_services
from api.analytics.homeworld_locator.baseline_ensure import (
    ensure_homeworld_baseline,
    needs_baseline_recompute,
)
from api.analytics.homeworld_locator.compute_services import (
    HomeworldLocatorComputeServices,
    resolve_homeworld_services,
)
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.evidence_ensure import (
    ensure_homeworld_evidence_refined,
    evidence_refined_through_shell,
)
from api.analytics.homeworld_locator.evidence_refine_report import build_ensure_failure_report
from api.analytics.homeworld_locator.evidence_refine_timing_history import (
    record_ensure_failure_report,
)
from api.analytics.homeworld_locator.fleet_built_turns import fleet_built_turns_from_final_ledgers
from api.analytics.homeworld_locator.serialization import (
    homeworld_candidate_record_to_json,
    homeworld_evidence_aggregate_to_json,
    homeworld_locator_game_state_to_json,
)
from api.analytics.turn_roster import iter_turn_players
from api.concepts.homeworld_layout import (
    homeworld_settings_fingerprint,
    is_homeworld_locator_available,
)
from api.errors import ValidationError
from api.models.game import TurnInfo

PATH_PREFIX_SCOPE_RULES: tuple[PathPrefixScopeRule, ...] = ()

# Baseline floor at turn 1 (or degraded earliest) plus linear self-chain for
# shell-turn evidence refine (#36). Ownership evidence (#269) waits on final
# fleet ledgers for every roster player at the shell turn (built_turn ages).
ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = (
    EnsureDependency(analytic_id=ANALYTIC_ID, turn_delta=-1, player_id="same"),
    EnsureDependency(analytic_id="fleet", turn_delta=0, player_id="all", quality="final"),
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
    reason: str,
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


def _raise_chain_fill_failure(scope: ExportScope, error: DependencyChainFillError) -> NoReturn:
    """Fail the shell turn when a chain hole could not be auto-fetched."""
    missing_turn = error.missing_turn
    if error.auto_fetch_unavailable:
        reason = "turn_not_stored"
        message = (
            f"homeworld locator cannot refine turn {scope.turn}: "
            f"turn {missing_turn} is not stored "
            f"(sign in to auto-fetch missing turns for the evidence chain)"
        )
    else:
        reason = "turn_fetch_failed"
        message = (
            f"homeworld locator cannot refine turn {scope.turn}: "
            f"could not load turn {missing_turn} from Planets.nu "
            f"(required for the evidence chain"
        )
        if error.fetched_turns:
            fetched = ",".join(str(turn_number) for turn_number in error.fetched_turns)
            message += f"; auto-fetched turns {fetched} before failure"
        message += ")"
    _record_ensure_failure_and_raise(
        scope,
        reason=reason,
        message=message,
        missing_turn=missing_turn,
    )


def _raise_dependency_ensure_unavailable(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    reason: UnavailableReason,
) -> NoReturn:
    """Fail the shell turn when the framework ensure walk cannot complete."""
    missing_turn: int | None = None
    if reason != "turn_not_stored":
        message = (
            f"homeworld locator cannot refine turn {scope.turn}: "
            f"evidence chain dependencies are unavailable ({reason})"
        )
    else:
        missing = missing_dependency_chain_turns(ctx, scope)
        missing_turn = missing[0] if missing else None
        message = (
            f"homeworld locator cannot refine turn {scope.turn}: "
            f"turn {missing_turn} is not stored "
            f"(evidence chain requires contiguous turns)"
            if missing_turn is not None
            else (
                f"homeworld locator cannot refine turn {scope.turn}: "
                f"an intermediate turn in the evidence chain is not stored"
            )
        )
    _record_ensure_failure_and_raise(
        scope,
        reason=reason,
        message=message,
        missing_turn=missing_turn,
    )


def _prepare_homeworld_ensure_chain(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    services: HomeworldLocatorComputeServices,
) -> None:
    """Auto-fetch missing dependency-chain turns before orchestrator DAG plan."""
    try:
        prepare_dependency_chain_turns(
            ctx,
            ANALYTIC_ID,
            scope,
            ensure_turn=services.ensure_turn,
        )
    except DependencyChainFillError as error:
        if error.auto_fetch_unavailable or error.reason == "turn_fetch_failed":
            _raise_chain_fill_failure(scope, error)
        _raise_dependency_ensure_unavailable(
            ctx,
            scope,
            cast(UnavailableReason, error.reason),
        )


def _fleet_built_turns_after_ensure(
    ctx: AnalyticQueryContext,
    turn: TurnInfo,
    services: HomeworldLocatorComputeServices,
) -> dict[int, int]:
    """Load ship ages from final fleet ledgers (deps already satisfied)."""
    fleet_services = resolve_fleet_services(ctx)
    return fleet_built_turns_from_final_ledgers(
        fleet_services.persistence,
        game_id=services.game_id,
        perspective=services.perspective,
        turn_number=turn.settings.turn,
        player_ids=[player.id for player in iter_turn_players(turn)],
    )


def ensure_homeworld_export(ctx: AnalyticQueryContext, scope: ExportScope) -> bool:
    """Bring homeworld export scope to satisfaction via orchestrator submit+wait."""
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

    services = resolve_homeworld_services(ctx)
    _prepare_homeworld_ensure_chain(ctx, scope, services)

    from api.compute.export_ensure import ensure_export_scope_via_orchestrator

    satisfied = ensure_export_scope_via_orchestrator(ctx, ANALYTIC_ID, scope)
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
    result = ensure_homeworld_baseline(services, shell_turn=turn)
    # Single-step refine at shell; prior turns already ensured via DAG unwind.
    shell_aggregate = ensure_homeworld_evidence_refined(
        services,
        shell_turn=turn,
        game_state_baseline_turn=result.game_state.baseline_turn,
        fleet_built_turns=_fleet_built_turns_after_ensure(ctx, turn, services),
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
