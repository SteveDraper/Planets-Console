"""Shared prior-fleet resolution for scores tier wire and ensure admit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.export_types import ExportScope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.prior_selection import select_fleet_prior_persisted
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

    Prefers a final DepOutputs / disk ledger via ``select_fleet_prior_persisted``,
    then falls back to ``resolve_prior_turn_fleet_torp_overlay``.
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

    prior_from_disk: PersistedFleetLedger | None = None
    fleet_services = fleet_compute_services(ctx)
    if fleet_services is not None:
        prior_from_disk = fleet_services.persistence.get_ledger(
            game_id,
            perspective,
            prior_fleet_scope.turn,
            prior_fleet_scope.player_id,
        )
    prior_persisted = select_fleet_prior_persisted(
        from_dependency_outputs=prior_from_deps,
        from_disk=prior_from_disk,
    )
    if prior_persisted is not None and prior_turn is not None:
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
