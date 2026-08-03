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
from api.analytics.homeworld_locator.evidence_ensure import (
    compute_homeworld_evidence_refine_step_detailed,
    ensure_evidence_floor_algorithm_current,
    evidence_refined_through_shell,
    record_evidence_refine_step_report,
)
from api.analytics.homeworld_locator.fleet_built_turns import (
    coerce_fleet_built_turns_map,
    fleet_built_turns_from_dependency_outputs,
)
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
from api.errors import ValidationError
from api.serialization.turn import turn_info_to_json

HOMEWORLD_BASELINE_STEP = "baseline"
HOMEWORLD_REFINE_STEP = "refine"

HOMEWORLD_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn"))

HOMEWORLD_COMPUTE_PROFILE = AnalyticComputeProfile(
    steps=(
        ComputeStepSpec(step_kind=HOMEWORLD_BASELINE_STEP, backend="inline"),
        ComputeStepSpec(step_kind=HOMEWORLD_REFINE_STEP, backend="inline"),
    ),
)

# Inline-only job-wire keys (not JSON-serializable across pool boundaries).
_COMPUTE_SERVICES_KEY = "computeServices"
_FLEET_BUILT_TURNS_KEY = "fleetBuiltTurns"


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

    Produces ``gameState`` + ``floorAggregate`` wires, then continues into the
    refine profile step (``persist_then_continue``) so refine is not decorative.
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
        persist_then_continue=True,
        payload={
            "available": True,
            "recomputed": result.recomputed,
            "gameState": homeworld_locator_game_state_to_json(result.game_state),
            "floorAggregate": homeworld_evidence_aggregate_to_json(result.floor_aggregate),
        },
    )


def build_homeworld_refine_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    **_kwargs: object,
) -> dict[str, Any]:
    if ctx is None:
        raise RuntimeError("homeworld refine job wire requires AnalyticQueryContext")
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        raise ValueError("homeworld refine requires concrete turn")
    if scope.perspective == WILDCARD or not isinstance(scope.perspective, int):
        raise ValueError("homeworld refine requires concrete perspective")

    export_scope = compute_scope_to_export_scope(scope)
    turn = ctx.load_turn(export_scope.turn)
    if turn is None:
        raise ValueError(f"stored turn {export_scope.turn} is required for homeworld refine")

    return {
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "shellTurn": scope.turn,
        "turnWire": turn_info_to_json(turn),
        "analyticId": ANALYTIC_ID,
        _COMPUTE_SERVICES_KEY: resolve_homeworld_services(ctx),
        _FLEET_BUILT_TURNS_KEY: fleet_built_turns_from_dependency_outputs(dependency_outputs),
    }


def run_homeworld_refine(job_wire: dict[str, Any]) -> StepResult:
    """Refine one turn of homeworld location evidence; persist via PersistencePolicy.

    Assumes prior-turn evidence exists via ``ENSURE_DEPENDENCIES`` DAG unwind.
    """
    from api.serialization.turn import turn_info_from_json

    turn_wire = job_wire.get("turnWire")
    if not isinstance(turn_wire, dict):
        raise TypeError("homeworld refine job wire requires turnWire object")
    settings_defaults = turn_wire.get("settings")
    if not isinstance(settings_defaults, dict):
        raise TypeError("homeworld refine turnWire.settings must be an object")
    turn = turn_info_from_json(turn_wire, settings_defaults=settings_defaults)

    if not is_homeworld_locator_available(turn.settings):
        return StepResult(outcome="complete", payload={"available": False})

    services = job_wire.get(_COMPUTE_SERVICES_KEY)
    if not isinstance(services, HomeworldLocatorComputeServices):
        raise TypeError(
            "homeworld refine job wire requires computeServices "
            f"(HomeworldLocatorComputeServices), got {type(services).__name__}"
        )

    state = services.persistence.get_game_state(services.game_id)
    if state is None:
        raise ValidationError("homeworld refine requires game-global state")

    shell_turn = turn.settings.turn
    fleet_built_turns = job_wire.get(_FLEET_BUILT_TURNS_KEY)
    if fleet_built_turns is not None and not isinstance(fleet_built_turns, dict):
        raise TypeError("homeworld refine job wire fleetBuiltTurns must be a dict when present")
    built_turn_map = coerce_fleet_built_turns_map(
        fleet_built_turns if isinstance(fleet_built_turns, dict) else None
    )

    already_durable = evidence_refined_through_shell(
        services,
        baseline_turn=state.baseline_turn,
        shell_turn=shell_turn,
    )
    if not already_durable:
        ensure_evidence_floor_algorithm_current(
            services,
            baseline_turn=state.baseline_turn,
            fleet_built_turns=built_turn_map,
        )
    step = compute_homeworld_evidence_refine_step_detailed(
        services,
        turn=turn,
        fleet_built_turns=built_turn_map,
    )
    # Persist timing is owned by PersistencePolicy; record refine compute cost here.
    if not already_durable:
        record_evidence_refine_step_report(services, turn=turn, step=step, persist_ms=0.0)
    payload = {
        "available": True,
        "evidenceAggregate": homeworld_evidence_aggregate_to_json(step.aggregate),
    }
    if already_durable:
        return StepResult(outcome="complete", payload=payload)
    return StepResult(outcome="persist", payload=payload)


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

        evidence_wire = result_wire.get("evidenceAggregate")
        if isinstance(evidence_wire, dict) and "gameState" not in result_wire:
            aggregate = homeworld_evidence_aggregate_from_json(evidence_wire)
            services = resolve_homeworld_services(ctx)
            services.persistence.put_evidence_aggregate(
                export_scope.game_id,
                export_scope.perspective,
                aggregate,
            )
            return

        game_state_wire = result_wire.get("gameState")
        floor_wire = result_wire.get("floorAggregate")
        if not isinstance(game_state_wire, dict):
            raise TypeError("homeworld persist result wire missing gameState object")
        if not isinstance(floor_wire, dict):
            raise TypeError("homeworld persist result wire missing floorAggregate object")

        recomputed = result_wire.get("recomputed")
        if not isinstance(recomputed, bool):
            raise TypeError("homeworld baseline persist result wire requires recomputed bool")

        services = resolve_homeworld_services(ctx)
        state = homeworld_locator_game_state_from_json(game_state_wire)
        floor = homeworld_evidence_aggregate_from_json(floor_wire)
        # Match ensure_homeworld_baseline: clear stale shell evidence only on recompute.
        # Evidence-only gaps re-enter at baseline with recomputed=False and must keep the chain.
        if recomputed:
            services.persistence.invalidate_evidence_from_turn(
                export_scope.game_id,
                export_scope.perspective,
                state.baseline_turn,
            )
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
