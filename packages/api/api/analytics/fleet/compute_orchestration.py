"""Fleet analytic compute orchestrator registration surface."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_to_json,
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import PersistedFleetLedger
from api.compute.profile import AnalyticComputeProfile, ComputeStepSpec
from api.compute.scope import (
    WILDCARD,
    ComputeScope,
    ScopeKeySpec,
    compute_scope_to_export_scope,
)
from api.compute.wire import DependencyOutputs
from api.serialization.turn import turn_info_to_json

FLEET_MATERIALIZATION_LEG = "materialization_leg"

# Two-phase fleet materialization:
# 1. Interpreter leg (materialization_leg) advances the ledger without inference.
# 2. FleetPersistencePolicy.persist refines inferred acquisitions from scores,
#    may re-resolve provenance, writes the refined ledger back onto result_wire,
#    then put_ledger. Stream listeners and DependencyOutputs priors read that wire.

FLEET_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn", "player_id"))

FLEET_COMPUTE_PROFILE = AnalyticComputeProfile(
    steps=(ComputeStepSpec(step_kind=FLEET_MATERIALIZATION_LEG, backend="interpreter"),),
)


def _fleet_prior_scope(scope: ComputeScope) -> ComputeScope | None:
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        return None
    if scope.turn <= 1:
        return None
    return ComputeScope(
        analytic_id=scope.analytic_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn - 1,
        player_id=scope.player_id,
        parameters=scope.parameters,
    )


def build_fleet_materialization_leg_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
) -> dict[str, Any]:
    """Assemble a serializable job wire for one fleet materialization leg.

    Embeds provenance at wire-build time for the interpreter leg; persist may
    re-resolve provenance after scores inference refines the ledger.
    """
    from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
    from api.analytics.fleet.compute_services import resolve_fleet_services
    from api.analytics.fleet.materialization_provenance import (
        resolve_fleet_materialization_provenance,
    )
    from api.analytics.fleet.turn_context import FleetTurnContext

    if ctx is None:
        raise RuntimeError("fleet materialization leg job wire requires AnalyticQueryContext")
    if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
        raise ValueError("fleet materialization leg requires concrete player_id")
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        raise ValueError("fleet materialization leg requires concrete turn")

    export_scope = compute_scope_to_export_scope(scope)
    turn = ctx.load_turn(export_scope.turn)
    if turn is None:
        raise ValueError(f"stored turn {export_scope.turn} is required for fleet materialization")

    player_id = scope.player_id
    services = resolve_fleet_services(ctx)
    prior_scope = _fleet_prior_scope(scope)
    prior_persisted: PersistedFleetLedger | None = None
    if prior_scope is not None:
        prior_wire = dependency_outputs.get(prior_scope)
        # Satisfaction short-circuit may leave ``{}`` (or a wire without ledger).
        # Treat missing ``persistedLedgerWire`` like an absent prior and reload.
        if isinstance(prior_wire, dict):
            persisted_wire = prior_wire.get("persistedLedgerWire")
            if isinstance(persisted_wire, dict):
                prior_persisted = persisted_fleet_ledger_from_json(persisted_wire)
        if prior_persisted is None:
            prior_persisted = services.persistence.get_ledger(
                scope.game_id,
                scope.perspective,
                prior_scope.turn,
                player_id,
            )

    if prior_persisted is None:
        baseline_ledger = ensure_fleet_baseline_for_player(
            scope.game_id,
            scope.perspective,
            turn,
            player_id,
        )
        baseline_ledger_wire = fleet_acquisition_ledger_to_json(baseline_ledger)
    else:
        baseline_ledger_wire = fleet_acquisition_ledger_to_json(prior_persisted.ledger)

    turn_context = FleetTurnContext.from_turn(turn)
    provenance = resolve_fleet_materialization_provenance(
        materialize_turn=scope.turn,
        prior_persisted=prior_persisted,
        turn_context=turn_context,
        player_id=player_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        load_turn=ctx.load_turn,
        inference_materialization=services.inference_materialization,
    )

    return {
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "playerId": player_id,
        "materializeTurn": scope.turn,
        "turnWire": turn_info_to_json(turn),
        "priorLedgerWire": (
            persisted_fleet_ledger_to_json(prior_persisted) if prior_persisted is not None else None
        ),
        "baselineLedgerWire": baseline_ledger_wire,
        "provenanceWire": {
            "turnEvidenceAtN": provenance.turn_evidence_at_n,
            "priorLedgerAtNMinus1": provenance.prior_ledger_at_n_minus_1,
        },
    }


class FleetPersistencePolicy:
    """Orchestrator persistence hooks for per-player fleet ledger scopes.

    ``persist`` is phase 2 of fleet materialization: when scores inference is
    wired it refines inferred acquisitions and re-resolves provenance before
    storing the ledger returned by the interpreter leg. The refined ledger is
    written back onto ``result_wire["persistedLedgerWire"]`` so node-complete
    listeners and in-run ``DependencyOutputs`` priors see post-refine state
    (not the phase-1 interpreter payload).
    """

    def is_satisfied(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> bool:
        from api.analytics.fleet.compute_services import resolve_fleet_services

        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            return False
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            return False
        services = resolve_fleet_services(ctx)
        return services.persistence.has_final_ledger(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
        )

    def satisfied_result_wire(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
    ) -> dict[str, object] | None:
        """Hydrate short-circuit completes with the durable final ledger wire."""
        from api.analytics.fleet.compute_services import resolve_fleet_services

        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            return None
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            return None
        services = resolve_fleet_services(ctx)
        persisted = services.persistence.get_ledger(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
        )
        if persisted is None or not persisted.provenance.is_final:
            return None
        return {"persistedLedgerWire": persisted_fleet_ledger_to_json(persisted)}

    def persist(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: object,
    ) -> Callable[[], None] | None:
        from api.analytics.fleet.compute_services import resolve_fleet_services
        from api.analytics.fleet.inferred_acquisition_refine import (
            refine_player_inferred_acquisitions_from_scores,
        )
        from api.analytics.fleet.materialization_provenance import (
            resolve_fleet_materialization_provenance,
        )
        from api.analytics.fleet.turn_context import FleetTurnContext

        if not isinstance(result_wire, dict):
            raise TypeError(f"fleet result wire must be dict, got {type(result_wire).__name__}")
        persisted_wire = result_wire.get("persistedLedgerWire")
        if not isinstance(persisted_wire, dict):
            raise TypeError("fleet result wire missing persistedLedgerWire object")
        persisted = persisted_fleet_ledger_from_json(persisted_wire)
        services = resolve_fleet_services(ctx)
        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            raise ValueError("fleet persist requires concrete player_id")
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            raise ValueError("fleet persist requires concrete turn")

        turn = ctx.load_turn(scope.turn)
        if turn is None:
            raise ValueError(f"stored turn {scope.turn} is required for fleet persist")

        if services.inference_materialization is not None:
            # Phase 2: scores inference may mutate the ledger and provenance.
            refine_player_inferred_acquisitions_from_scores(
                persisted.ledger,
                turn,
                game_id=scope.game_id,
                perspective=scope.perspective,
                inference_materialization=services.inference_materialization,
            )
            turn_context = FleetTurnContext.from_turn(turn)
            prior_scope = _fleet_prior_scope(scope)
            prior_persisted = None
            if prior_scope is not None:
                prior_ledger = services.persistence.get_ledger(
                    scope.game_id,
                    scope.perspective,
                    prior_scope.turn,
                    scope.player_id,
                )
                prior_persisted = prior_ledger
            provenance = resolve_fleet_materialization_provenance(
                materialize_turn=scope.turn,
                prior_persisted=prior_persisted,
                turn_context=turn_context,
                player_id=scope.player_id,
                game_id=scope.game_id,
                perspective=scope.perspective,
                load_turn=services.load_turn,
                inference_materialization=services.inference_materialization,
            )
            persisted = PersistedFleetLedger(ledger=persisted.ledger, provenance=provenance)

        if not persisted.provenance.turn_evidence_at_n:
            # Same-turn scores evidence is still open. Persisting and completing the
            # fleet node would unlock dependents and park a non-final ledger with no
            # automatic rematerialization (empty scores complete hang fingerprint).
            from api.errors import FleetScoresEvidenceOpenError

            raise FleetScoresEvidenceOpenError(
                f"fleet persist refused for game {scope.game_id} perspective "
                f"{scope.perspective} player {scope.player_id} turn {scope.turn}: "
                "scores turn evidence is not closed"
            )

        # Stamp current materialization version and publish onto result_wire so
        # stream listeners and DependencyOutputs match what put_ledger stores.
        persisted = PersistedFleetLedger(
            ledger=persisted.ledger,
            provenance=persisted.provenance,
            materialization_version=FLEET_MATERIALIZATION_VERSION,
        )
        result_wire["persistedLedgerWire"] = persisted_fleet_ledger_to_json(persisted)

        return services.persistence.put_ledger(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
            persisted,
            defer_ledger_persisted_notification=True,
            notification_source_context_id=id(ctx),
        )

    def invalidate(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> None:
        from api.analytics.fleet.compute_services import resolve_fleet_services

        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            return
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            return
        services = resolve_fleet_services(ctx)
        services.persistence.invalidate_player_ledgers_from_turn(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
        )

    def invalidation_generation(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
        from api.analytics.fleet.compute_services import resolve_fleet_services

        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            return 0
        services = resolve_fleet_services(ctx)
        return services.persistence.invalidation_generation(
            scope.game_id,
            scope.perspective,
            scope.player_id,
        )


FLEET_PERSISTENCE_POLICY = FleetPersistencePolicy()
