"""Fleet analytic compute orchestrator registration surface."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.eliminated_player import fleet_player_eliminated_at_turn
from api.analytics.fleet.prior_selection import resolve_fleet_prior_persisted
from api.analytics.fleet.scoreboard_slice import fleet_scoreboard_slice_to_json
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
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import GameSettings

if TYPE_CHECKING:
    from api.analytics.fleet.compute_services import FleetComputeServices
    from api.compute.orchestrator import ComputeOrchestrator
    from api.models.game import TurnInfo

FLEET_OBSERVATION_LEG = "observation_leg"
FLEET_FINALIZATION_LEG = "finalization_leg"
# Legacy alias for tests and diagnostics that still name the interpreter leg.
FLEET_MATERIALIZATION_LEG = FLEET_OBSERVATION_LEG

# Two-phase fleet materialization:
# 1. Observation passes the prior through. Persist copies it, matches this
#    turn's sightings, and writes the approximate file (never ensure-final).
# 2. Finalization replaces that file once the same-turn scoreboard is terminal.

FLEET_SCOPE_KEY_SPEC = ScopeKeySpec(axes=("perspective", "turn", "player_id"))

FLEET_COMPUTE_PROFILE = AnalyticComputeProfile(
    steps=(
        ComputeStepSpec(
            step_kind=FLEET_OBSERVATION_LEG,
            backend="interpreter",
        ),
        ComputeStepSpec(step_kind=FLEET_FINALIZATION_LEG, backend="inline"),
    ),
)


def _fleet_prior_scope(
    scope: ComputeScope,
    *,
    settings: GameSettings,
) -> ComputeScope | None:
    if scope.turn == WILDCARD or not isinstance(scope.turn, int):
        return None
    if scope.turn <= accelerated_ensure_floor(settings, scope.turn):
        return None
    return ComputeScope(
        analytic_id=scope.analytic_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn - 1,
        player_id=scope.player_id,
        parameters=scope.parameters,
    )


def build_fleet_observation_leg_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    **_kwargs: object,
) -> dict[str, Any]:
    """Assemble a serializable job wire for one fleet observation leg."""
    return build_fleet_materialization_leg_job_wire(
        scope,
        dependency_outputs=dependency_outputs,
        ctx=ctx,
    )


def build_fleet_materialization_leg_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    **_kwargs: object,
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
    if fleet_player_eliminated_at_turn(turn, player_id):
        return _eliminated_fleet_job_wire(scope, player_id=player_id)

    services = resolve_fleet_services(ctx)
    prior_scope = _fleet_prior_scope(scope, settings=turn.settings)
    prior_persisted: PersistedFleetLedger | None = None
    if prior_scope is not None:
        prior_from_deps: PersistedFleetLedger | None = None
        prior_wire = dependency_outputs.get(prior_scope)
        # Satisfaction short-circuit may leave ``{}`` (or a wire without ledger).
        # Treat missing ``persistedLedgerWire`` like an absent prior and reload.
        if isinstance(prior_wire, dict):
            persisted_wire = prior_wire.get("persistedLedgerWire")
            if isinstance(persisted_wire, dict):
                prior_from_deps = persisted_fleet_ledger_from_json(persisted_wire)
        prior_persisted = resolve_fleet_prior_persisted(
            from_dependency_outputs=prior_from_deps,
            load_from_disk=lambda: services.persistence.get_ledger(
                scope.game_id,
                scope.perspective,
                prior_scope.turn,
                player_id,
            ),
            is_ensure_final=lambda persisted: services.persistence.ledger_is_ensure_final(
                scope.game_id,
                scope.perspective,
                prior_scope.turn,
                player_id,
                persisted,
            ),
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
    prior_is_ensure_final = False
    if prior_persisted is not None and prior_scope is not None:
        prior_is_ensure_final = services.persistence.ledger_is_ensure_final(
            scope.game_id,
            scope.perspective,
            prior_scope.turn,
            player_id,
            prior_persisted,
        )
    provenance = resolve_fleet_materialization_provenance(
        materialize_turn=scope.turn,
        prior_is_ensure_final=prior_is_ensure_final,
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
        "turnWire": fleet_scoreboard_slice_to_json(turn),
        "priorLedgerWire": (
            persisted_fleet_ledger_to_json(prior_persisted) if prior_persisted is not None else None
        ),
        "baselineLedgerWire": baseline_ledger_wire,
        "provenanceWire": {
            "turnEvidenceAtN": provenance.turn_evidence_at_n,
            "priorLedgerAtNMinus1": provenance.prior_ledger_at_n_minus_1,
        },
    }


def _eliminated_fleet_job_wire(
    scope: ComputeScope,
    *,
    player_id: int,
) -> dict[str, Any]:
    """Job wire for an eliminated player: flag only, no prior or baseline.

    The observation leg builds the empty non-final ledger from the flag.
    Finalization persist rebuilds the empty final ledger from the loaded turn.
    """
    return {
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "playerId": player_id,
        "materializeTurn": scope.turn,
        "priorLedgerWire": None,
        "baselineLedgerWire": None,
        "eliminatedAtTurn": True,
    }


def build_fleet_finalization_leg_job_wire(
    scope: ComputeScope,
    *,
    dependency_outputs: DependencyOutputs,
    ctx: AnalyticQueryContext | None = None,
    node_result_wire: object | None = None,
) -> dict[str, Any]:
    """Pass the observation continue wire into the inline finalization leg."""
    del dependency_outputs, ctx
    if not isinstance(node_result_wire, dict):
        raise RuntimeError("fleet finalization leg requires observation result wire on node")
    return dict(node_result_wire)


class FleetPersistencePolicy:
    """Orchestrator persistence hooks for per-player fleet ledger scopes.

    Observation persist writes the approximate fleet. Finalization replaces
    that file when the same-turn scoreboard is terminal, and leaves it in place
    when the scoreboard row is not. The stored ledger is written back onto
    ``result_wire["persistedLedgerWire"]`` so listeners and in-run priors see
    the file, not the pre-persist interpreter payload.
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
        if persisted is None or not services.persistence.ledger_is_ensure_final(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
            persisted,
        ):
            return None
        return {"persistedLedgerWire": persisted_fleet_ledger_to_json(persisted)}

    def persist(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: object,
    ) -> Callable[[], None] | None:
        if not isinstance(result_wire, dict):
            raise TypeError(f"fleet result wire must be dict, got {type(result_wire).__name__}")
        persist_leg = result_wire.get("fleetPersistLeg")
        if persist_leg == "observation":
            return self._persist_observation(ctx, scope, result_wire)
        return self._persist_finalization(ctx, scope, result_wire)

    def _persist_observation(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: dict[str, object],
    ) -> Callable[[], None] | None:
        from api.analytics.fleet.approximate_fleet import approximate_fleet_ledger
        from api.analytics.fleet.compute_services import resolve_fleet_services
        from api.analytics.fleet.fleet_table_stream_scheduler import publish_saved_host_turn_ledger
        from api.analytics.fleet.types import FleetMaterializationProvenance

        persisted_wire = result_wire.get("persistedLedgerWire")
        if not isinstance(persisted_wire, dict):
            raise TypeError("fleet observation wire missing persistedLedgerWire object")
        persisted = persisted_fleet_ledger_from_json(persisted_wire)
        services = resolve_fleet_services(ctx)
        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            raise ValueError("fleet observation persist requires concrete player_id")
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            raise ValueError("fleet observation persist requires concrete turn")

        turn = ctx.load_turn(scope.turn)
        eliminated = result_wire.get("eliminatedAtTurn") is True or (
            turn is not None and fleet_player_eliminated_at_turn(turn, scope.player_id)
        )
        if not eliminated:
            if turn is None:
                raise ValueError(f"stored turn {scope.turn} is required for fleet persist")
            ledger = approximate_fleet_ledger(
                persisted.ledger,
                turn,
                perspective=scope.perspective,
            )
            persisted = PersistedFleetLedger(
                ledger=ledger,
                provenance=persisted.provenance,
            )

        # Observation must never claim ensure-final. Only finalization may set
        # turnEvidenceAtN or eliminatedAtTurn and satisfy has_final_ledger.
        persisted = PersistedFleetLedger(
            ledger=persisted.ledger,
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=False,
                prior_ledger_at_n_minus_1=persisted.provenance.prior_ledger_at_n_minus_1,
            ),
            materialization_version=persisted.materialization_version,
        )
        put_result = services.persistence.put_ledger(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
            persisted,
            defer_ledger_persisted_notification=True,
        )
        result_wire["persistedLedgerWire"] = persisted_fleet_ledger_to_json(put_result.stored)
        if eliminated:
            return None
        publish_saved_host_turn_ledger(
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn_number=scope.turn,
            player_id=scope.player_id,
            persisted=put_result.stored,
        )
        return self._refresh_following_callback(services, scope)

    def _persist_finalization(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: dict[str, object],
    ) -> Callable[[], None] | None:
        from api.analytics.fleet.compute_services import resolve_fleet_services
        from api.analytics.fleet.materialization_provenance import (
            resolve_fleet_materialization_provenance,
        )
        from api.analytics.fleet.turn_context import FleetTurnContext

        if not isinstance(result_wire, dict):
            raise TypeError(f"fleet result wire must be dict, got {type(result_wire).__name__}")
        persisted_wire = result_wire.get("persistedLedgerWire")
        if not isinstance(persisted_wire, dict):
            raise TypeError("fleet result wire missing persistedLedgerWire object")
        wire_ledger = persisted_fleet_ledger_from_json(persisted_wire)
        services = resolve_fleet_services(ctx)
        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            raise ValueError("fleet persist requires concrete player_id")
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            raise ValueError("fleet persist requires concrete turn")
        if wire_ledger.ledger.player_id != scope.player_id:
            raise ValueError("fleet persist ledger player does not match scope")

        turn = ctx.load_turn(scope.turn)
        if turn is None:
            raise ValueError(f"stored turn {scope.turn} is required for fleet persist")

        if fleet_player_eliminated_at_turn(turn, scope.player_id):
            return self._persist_eliminated_empty(ctx, scope, result_wire, turn)
        turn_context = FleetTurnContext.from_turn(turn)

        prior_scope = _fleet_prior_scope(scope, settings=turn.settings)
        prior_on_disk = None
        prior_is_ensure_final = False
        if prior_scope is not None:
            prior_on_disk = services.persistence.get_ledger(
                scope.game_id,
                scope.perspective,
                prior_scope.turn,
                scope.player_id,
            )
            if prior_on_disk is not None:
                prior_is_ensure_final = services.persistence.ledger_is_ensure_final(
                    scope.game_id,
                    scope.perspective,
                    prior_scope.turn,
                    scope.player_id,
                    prior_on_disk,
                )
        provenance = resolve_fleet_materialization_provenance(
            materialize_turn=scope.turn,
            prior_is_ensure_final=prior_is_ensure_final,
            turn_context=turn_context,
            player_id=scope.player_id,
            game_id=scope.game_id,
            perspective=scope.perspective,
            load_turn=services.load_turn,
            inference_materialization=services.inference_materialization,
        )

        if not provenance.turn_evidence_at_n:
            # Same-turn scores evidence is still open. Persisting and completing the
            # fleet node would unlock dependents and leave a non-final ledger with no
            # automatic rematerialization (empty scores complete hang fingerprint).
            # PersistDependencyRecovery.force_fresh is the sole reopen mechanism here:
            # the orchestrator's persist-deferred recovery submits the scores scope
            # with force_fresh=True, which refreshes waiting_deps / absent / terminal
            # nodes alike. Do not also call wake_scores_scope for this path -- that
            # would be a second encoding of the same reopen policy.
            from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
            from api.compute.persistence import PersistDependencyRecovery
            from api.errors import FleetScoresEvidenceOpenError

            scores_scope = ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=scope.game_id,
                perspective=scope.perspective,
                turn=scope.turn,
                player_id=scope.player_id,
                parameters=scope.parameters,
            )
            raise FleetScoresEvidenceOpenError(
                f"fleet persist refused for game {scope.game_id} perspective "
                f"{scope.perspective} player {scope.player_id} turn {scope.turn}: "
                "scores turn evidence is not closed",
                recovery=PersistDependencyRecovery(
                    dependency_scope=scores_scope,
                    force_fresh=True,
                    step_kind="tier_solve",
                ),
            )

        from api.analytics.fleet.approximate_fleet import terminal_fleet_ledger
        from api.analytics.fleet.chain import ensure_fleet_baseline_for_player

        if prior_on_disk is not None:
            prior_ledger = prior_on_disk.ledger
        else:
            prior_ledger = ensure_fleet_baseline_for_player(
                scope.game_id,
                scope.perspective,
                turn,
                scope.player_id,
            )
        ledger = terminal_fleet_ledger(
            prior_ledger,
            turn,
            game_id=scope.game_id,
            perspective=scope.perspective,
            inference_materialization=services.inference_materialization,
            turn_context=turn_context,
        )
        return self._commit_living_final(
            services,
            scope,
            result_wire,
            PersistedFleetLedger(
                ledger=ledger,
                provenance=provenance,
                materialization_version=FLEET_MATERIALIZATION_VERSION,
            ),
        )

    def _commit_living_final(
        self,
        services: FleetComputeServices,
        scope: ComputeScope,
        result_wire: dict[str, object],
        persisted: PersistedFleetLedger,
    ) -> Callable[[], None]:
        """Store a living final ledger, then wake scores and later approximate files."""
        from api.analytics.fleet.compute_services import FleetComputeServices

        if not isinstance(services, FleetComputeServices):
            raise TypeError("fleet finalization persist requires FleetComputeServices")
        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            raise ValueError("fleet finalization persist requires concrete player_id")
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            raise ValueError("fleet finalization persist requires concrete turn")
        put_result = services.persistence.put_ledger(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
            persisted,
            defer_ledger_persisted_notification=True,
        )
        result_wire["persistedLedgerWire"] = persisted_fleet_ledger_to_json(put_result.stored)
        scores_notification = put_result.deferred_notification
        refresh = self._refresh_following_callback(services, scope)

        def _after_final_save() -> None:
            if scores_notification is not None:
                scores_notification()
            refresh()

        return _after_final_save

    def _refresh_following_callback(
        self,
        services: FleetComputeServices,
        scope: ComputeScope,
    ) -> Callable[[], None]:
        """Replace later approximate files from the ledger this persist just saved."""
        from api.analytics.fleet.approximate_fleet import refresh_following_approximate_fleets
        from api.analytics.fleet.compute_services import FleetComputeServices

        if not isinstance(services, FleetComputeServices):
            raise TypeError("fleet later-file refresh requires FleetComputeServices")
        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            raise ValueError("fleet later-file refresh requires concrete player_id")
        if scope.turn == WILDCARD or not isinstance(scope.turn, int):
            raise ValueError("fleet later-file refresh requires concrete turn")
        player_id = scope.player_id
        saved_turn = scope.turn

        def _refresh() -> None:
            refresh_following_approximate_fleets(
                persistence=services.persistence,
                game_id=scope.game_id,
                perspective=scope.perspective,
                player_id=player_id,
                saved_turn=saved_turn,
                load_turn=services.load_turn,
                inference_materialization=services.inference_materialization,
            )

        return _refresh

    def _persist_eliminated_empty(
        self,
        ctx: AnalyticQueryContext,
        scope: ComputeScope,
        result_wire: dict[str, object],
        turn: TurnInfo,
    ) -> Callable[[], None] | None:
        """Write an empty final ledger. Does not wait on scores or a prior fleet."""
        from api.analytics.fleet.compute_services import resolve_fleet_services
        from api.analytics.fleet.eliminated_player import (
            eliminated_empty_fleet_ledger,
            eliminated_fleet_provenance,
        )

        if not isinstance(scope.player_id, int):
            raise ValueError("eliminated fleet persist requires concrete player_id")
        if not isinstance(scope.turn, int):
            raise ValueError("eliminated fleet persist requires concrete turn")
        services = resolve_fleet_services(ctx)
        persisted = PersistedFleetLedger(
            ledger=eliminated_empty_fleet_ledger(turn, scope.player_id),
            provenance=eliminated_fleet_provenance(),
            materialization_version=FLEET_MATERIALIZATION_VERSION,
        )
        put_result = services.persistence.put_ledger(
            scope.game_id,
            scope.perspective,
            scope.turn,
            scope.player_id,
            persisted,
            defer_ledger_persisted_notification=True,
        )
        result_wire["persistedLedgerWire"] = persisted_fleet_ledger_to_json(put_result.stored)
        return put_result.deferred_notification

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
            durable=True,
        )

    def invalidation_generation(self, ctx: AnalyticQueryContext, scope: ComputeScope) -> int:
        from api.analytics.fleet.compute_services import resolve_fleet_services

        if scope.player_id == WILDCARD or not isinstance(scope.player_id, int):
            return 0
        services = resolve_fleet_services(ctx)
        return services.persistence.player_invalidation_generation(
            scope.game_id,
            scope.perspective,
            scope.player_id,
        )


FLEET_PERSISTENCE_POLICY = FleetPersistencePolicy()


def wake_fleet_scope(
    scope: ComputeScope,
    *,
    priority_band: str = "background",
    orchestrator: ComputeOrchestrator | None = None,
) -> bool:
    """force_fresh-submit a fleet scope after durable wipe when no table stream is open.

    Uses the node's retained orchestration bundle so a hollow terminal (durable
    ledger gone, DAG still ``complete``) can be replaced without a live stream.
    In-flight nodes attach; ``force_fresh`` never supersedes ``running``. No-op
    when the process orchestrator has no node for the scope, or the node has no
    bundle.
    """
    from api.compute.orchestrator import ComputeRequest
    from api.compute.runtime import get_compute_orchestrator

    resolved_orchestrator = orchestrator or get_compute_orchestrator()
    node = resolved_orchestrator.nodes.get(scope)
    if node is None or node.bundle is None:
        return False
    resolved_orchestrator.submit(
        ComputeRequest(
            scope=scope,
            force_fresh=True,
            bundle=node.bundle,
            priority_band=priority_band,
        )
    )
    return True
