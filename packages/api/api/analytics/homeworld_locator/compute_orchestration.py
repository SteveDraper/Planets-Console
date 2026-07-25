"""Homeworld locator compute orchestrator registration surface."""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.homeworld_locator.baseline_ensure import compute_homeworld_baseline
from api.analytics.homeworld_locator.compute_services import (
    HomeworldLocatorComputeServices,
    resolve_homeworld_services,
)
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.serialization import (
    homeworld_evidence_aggregate_from_json,
    homeworld_evidence_aggregate_to_json,
    homeworld_locator_game_state_from_json,
    homeworld_locator_game_state_to_json,
)
from api.compute.profile import AnalyticComputeProfile, ComputeStepSpec
from api.compute.scope import WILDCARD, ComputeScope, ScopeKeySpec, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs, StepResult
from api.concepts.homeworld_layout import is_homeworld_locator_available
from api.serialization.turn import turn_info_to_json

HOMEWORLD_BASELINE_STEP = "baseline"

HOMEWORLD_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn"))

HOMEWORLD_COMPUTE_PROFILE = AnalyticComputeProfile(
    steps=(ComputeStepSpec(step_kind=HOMEWORLD_BASELINE_STEP, backend="inline"),),
)

# Inline-only job-wire key: HomeworldLocatorComputeServices (not JSON-serializable).
_COMPUTE_SERVICES_KEY = "computeServices"


def build_homeworld_baseline_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    **_kwargs: object,
) -> dict[str, Any]:
    """Assemble a job wire for baseline-only homeworld compute.

    Attaches ``computeServices`` for the inline step (same process; not pool-safe).
    """
    del dependency_outputs
    if ctx is None:
        raise RuntimeError("homeworld baseline job wire requires AnalyticQueryContext")
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        raise ValueError("homeworld baseline requires concrete turn")
    if scope.perspective == WILDCARD or not isinstance(scope.perspective, int):
        raise ValueError("homeworld baseline requires concrete perspective")

    export_scope = compute_scope_to_export_scope(scope)
    turn = ctx.load_turn(export_scope.turn)
    if turn is None:
        raise ValueError(f"stored turn {export_scope.turn} is required for homeworld baseline")

    return {
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "shellTurn": scope.turn,
        "turnWire": turn_info_to_json(turn),
        "analyticId": ANALYTIC_ID,
        _COMPUTE_SERVICES_KEY: resolve_homeworld_services(ctx),
    }


def run_homeworld_baseline(job_wire: dict[str, Any]) -> StepResult:
    """Compute baseline inference; durable write via PersistencePolicy.persist.

    Produces ``gameState`` + ``floorAggregate`` wires. Map/table/export still call
    ``ensure_homeworld_baseline`` directly (compute + write) as the interim path.
    """
    from api.serialization.turn import turn_info_from_json

    turn_wire = job_wire.get("turnWire")
    if not isinstance(turn_wire, dict):
        raise TypeError("homeworld baseline job wire requires turnWire object")
    settings_defaults = turn_wire.get("settings")
    if not isinstance(settings_defaults, dict):
        raise TypeError("homeworld baseline turnWire.settings must be an object")
    turn = turn_info_from_json(turn_wire, settings_defaults=settings_defaults)

    if not is_homeworld_locator_available(turn.settings):
        return StepResult(outcome="complete", payload={"available": False})

    services = job_wire.get(_COMPUTE_SERVICES_KEY)
    if not isinstance(services, HomeworldLocatorComputeServices):
        raise TypeError(
            "homeworld baseline job wire requires computeServices "
            f"(HomeworldLocatorComputeServices), got {type(services).__name__}"
        )

    result = compute_homeworld_baseline(services, shell_turn=turn)
    return StepResult(
        outcome="persist",
        payload={
            "available": True,
            "gameState": homeworld_locator_game_state_to_json(result.game_state),
            "floorAggregate": homeworld_evidence_aggregate_to_json(result.floor_aggregate),
        },
    )


class HomeworldLocatorPersistencePolicy:
    """Orchestrator persistence hooks for homeworld locator scopes."""

    def is_satisfied(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> bool:
        from api.analytics.homeworld_locator.exports import is_homeworld_export_ensure_satisfied

        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return False
        return is_homeworld_export_ensure_satisfied(ctx, export_scope)

    def satisfied_result_wire(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
    ) -> object | None:
        del ctx, scope
        return None

    def persist(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: object,
    ) -> None:
        if not isinstance(result_wire, dict):
            raise TypeError(
                f"homeworld persist result wire must be dict, got {type(result_wire).__name__}"
            )
        if result_wire.get("available") is False:
            return
        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return
        game_state_wire = result_wire.get("gameState")
        floor_wire = result_wire.get("floorAggregate")
        if not isinstance(game_state_wire, dict):
            raise TypeError("homeworld persist result wire missing gameState object")
        if not isinstance(floor_wire, dict):
            raise TypeError("homeworld persist result wire missing floorAggregate object")

        services = resolve_homeworld_services(ctx)
        state = homeworld_locator_game_state_from_json(game_state_wire)
        floor = homeworld_evidence_aggregate_from_json(floor_wire)
        services.persistence.put_baseline(
            export_scope.game_id,
            export_scope.perspective,
            state,
            floor,
        )

    def invalidate(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> None:
        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return
        services = resolve_homeworld_services(ctx)
        services.persistence.invalidate_evidence_from_turn(
            export_scope.game_id,
            export_scope.perspective,
            export_scope.turn,
        )

    def invalidation_generation(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
        export_scope = _export_scope_for_compute(scope)
        if export_scope is None:
            return 0
        services = resolve_homeworld_services(ctx)
        return services.persistence.invalidation_generation(
            export_scope.game_id,
            export_scope.perspective,
        )


def _export_scope_for_compute(scope: ComputeScope):
    from api.analytics.export_types import ExportScope

    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        return None
    if scope.perspective == WILDCARD or not isinstance(scope.perspective, int):
        return None
    return ExportScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=None,
    )


HOMEWORLD_PERSISTENCE_POLICY = HomeworldLocatorPersistencePolicy()
