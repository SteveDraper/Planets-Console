"""Shared prior-fleet resolution for scores tier wire and ensure admit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.export_types import ExportScope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.prior_selection import resolve_fleet_prior_persisted
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.analytics.fleet.types import FleetTurnSnapshot, PersistedFleetLedger
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
    records_for_scope,
    resolution_from_fleet_records,
    resolve_prior_turn_fleet_torp_overlay,
)
from api.compute.scope import WILDCARD, ComputeScope, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import GameSettings, TurnInfo

if TYPE_CHECKING:
    from api.analytics.fleet.compute_services import FleetComputeServices


def fleet_compute_services(ctx: AnalyticQueryContext) -> FleetComputeServices | None:
    """Resolve fleet compute services from export registration or injected map."""
    from api.analytics.fleet.compute_services import FleetComputeServices

    fleet_services = export_service_for(ctx, FLEET_ANALYTIC_ID, FleetComputeServices)
    if fleet_services is not None:
        return fleet_services
    injected = ctx.export_services.get(FLEET_ANALYTIC_ID)
    if isinstance(injected, FleetComputeServices):
        return injected
    return None


def prior_fleet_compute_scope(
    *,
    game_id: str,
    perspective: int,
    turn: int,
    player_id: int,
    settings: GameSettings,
) -> ComputeScope | None:
    """Fleet scope for scores@N prior (fleet@(N-1)), or None when not applicable."""
    if turn <= accelerated_ensure_floor(settings, turn):
        return None
    return ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=game_id,
        perspective=perspective,
        turn=turn - 1,
        player_id=player_id,
    )


def _resolution_from_persisted_fleet(
    persisted: PersistedFleetLedger,
    export_scope: ExportScope,
    *,
    prior_turn: TurnInfo,
) -> PriorTurnFleetTorpResolution:
    snapshot = FleetTurnSnapshot(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=export_scope.game_id,
        perspective=export_scope.perspective,
        turn=export_scope.turn,
        players=[persisted.ledger],
    )
    records = records_for_scope(snapshot, export_scope)
    return resolution_from_fleet_records(records, prior_turn=prior_turn)


def resolve_prior_fleet_for_scores(
    ctx: AnalyticQueryContext,
    *,
    game_id: str,
    perspective: int,
    turn_number: int,
    player_id: int,
    turn: TurnInfo,
    dependency_outputs: DependencyOutputs | None = None,
    overlay_ensure: bool = False,
) -> PriorTurnFleetTorpResolution:
    """Resolve prior-turn fleet torp overlay for scores wire build and ensure admit.

    Prefers an ensure-final DepOutputs / disk ledger via
    ``resolve_fleet_prior_persisted``. Applies that ledger only when it passes
    ``prior_is_ensure_final``; otherwise falls back to
    ``resolve_prior_turn_fleet_torp_overlay``. A readable non-final prior is
    never applied as the scores overlay.
    """
    if turn_number == WILDCARD or not isinstance(turn_number, int):
        return PriorTurnFleetTorpResolution(overlay=None, input_status="pending")
    if player_id == WILDCARD or not isinstance(player_id, int):
        return PriorTurnFleetTorpResolution(overlay=None, input_status="pending")

    prior_fleet_scope = prior_fleet_compute_scope(
        game_id=game_id,
        perspective=perspective,
        turn=turn_number,
        player_id=player_id,
        settings=turn.settings,
    )
    if prior_fleet_scope is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="not_applicable")

    prior_export_scope = compute_scope_to_export_scope(prior_fleet_scope)
    prior_turn = ctx.load_turn(prior_fleet_scope.turn)

    prior_from_deps: PersistedFleetLedger | None = None
    if dependency_outputs is not None:
        fleet_result_wire = dependency_outputs.get(prior_fleet_scope)
        # Satisfaction short-circuit may leave ``{}`` (or a wire without ledger).
        # Treat missing ``persistedLedgerWire`` like an absent prior and reload.
        if isinstance(fleet_result_wire, dict):
            persisted_wire = fleet_result_wire.get("persistedLedgerWire")
            if isinstance(persisted_wire, dict):
                prior_from_deps = persisted_fleet_ledger_from_json(persisted_wire)

    fleet_services = fleet_compute_services(ctx)

    def load_prior_from_disk() -> PersistedFleetLedger | None:
        if fleet_services is None:
            return None
        return fleet_services.persistence.get_ledger(
            game_id,
            perspective,
            prior_fleet_scope.turn,
            prior_fleet_scope.player_id,
        )

    def prior_is_ensure_final(persisted: PersistedFleetLedger) -> bool:
        # Without fleet services the evidence mark cannot be read; provenance
        # alone is not ensure-final for scores overlay admission.
        if fleet_services is None:
            return False
        return fleet_services.persistence.ledger_is_ensure_final(
            game_id,
            perspective,
            prior_fleet_scope.turn,
            prior_fleet_scope.player_id,
            persisted,
        )

    prior_persisted = resolve_fleet_prior_persisted(
        from_dependency_outputs=prior_from_deps,
        load_from_disk=load_prior_from_disk,
        is_ensure_final=prior_is_ensure_final,
    )
    # ``resolve_fleet_prior_persisted`` may still return a non-final ledger for
    # fleet job-wire baseline use; scores applies only ensure-final priors.
    if (
        prior_persisted is not None
        and prior_is_ensure_final(prior_persisted)
        and prior_turn is not None
    ):
        return _resolution_from_persisted_fleet(
            prior_persisted,
            prior_export_scope,
            prior_turn=prior_turn,
        )

    return resolve_prior_turn_fleet_torp_overlay(
        turn=turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        query_context=ctx,
        ensure=overlay_ensure,
    )
