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
from api.analytics.homeworld_locator.evidence_ensure import evidence_refined_through_shell
from api.analytics.homeworld_locator.evidence_refine import (
    candidate_planet_ids_from_records,
    refine_homeworld_evidence_aggregate,
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


def build_homeworld_refine_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    **_kwargs: object,
) -> dict[str, Any]:
    del dependency_outputs
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
    }


def run_homeworld_refine(job_wire: dict[str, Any]) -> StepResult:
    """Refine one turn of homeworld location evidence; persist via PersistencePolicy."""
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
    if shell_turn <= state.baseline_turn:
        floor = services.persistence.get_evidence_aggregate(
            services.game_id,
            services.perspective,
            state.baseline_turn,
        )
        if floor is None:
            raise ValidationError("homeworld refine requires baseline floor aggregate")
        return StepResult(
            outcome="complete",
            payload={
                "available": True,
                "evidenceAggregate": homeworld_evidence_aggregate_to_json(floor),
            },
        )

    if evidence_refined_through_shell(
        services,
        baseline_turn=state.baseline_turn,
        shell_turn=shell_turn,
    ):
        aggregate = services.persistence.get_evidence_aggregate(
            services.game_id,
            services.perspective,
            shell_turn,
        )
        if aggregate is None:
            raise ValidationError("homeworld refine satisfaction probe missing aggregate")
        return StepResult(
            outcome="complete",
            payload={
                "available": True,
                "evidenceAggregate": homeworld_evidence_aggregate_to_json(aggregate),
            },
        )

    prior_turn = shell_turn - 1
    prior = services.persistence.get_evidence_aggregate(
        services.game_id,
        services.perspective,
        prior_turn,
    )
    if prior is None:
        raise ValidationError(f"homeworld refine requires evidence aggregate at turn {prior_turn}")

    candidate_ids = candidate_planet_ids_from_records(state.candidates)
    planets_by_id = {planet.id: planet for planet in turn.planets}
    refined = refine_homeworld_evidence_aggregate(
        prior,
        turn=turn,
        candidate_planet_ids_set=candidate_ids,
        planets_by_id=planets_by_id,
    )
    return StepResult(
        outcome="persist",
        payload={
            "available": True,
            "evidenceAggregate": homeworld_evidence_aggregate_to_json(refined),
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
