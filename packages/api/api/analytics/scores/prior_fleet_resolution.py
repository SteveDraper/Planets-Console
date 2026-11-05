"""Shared prior-fleet resolution for scores tier wire and ensure admit."""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.injected_services import (
    FleetComputeServices,
    lookup_fleet_compute_services,
)
from api.analytics.fleet.prior_selection import resolve_fleet_prior_persisted
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.analytics.fleet.types import FleetTurnSnapshot, PersistedFleetLedger
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
    records_for_scope,
    resolution_from_fleet_records,
    resolve_prior_turn_fleet_torp_overlay,
)
from api.analytics.off_mode import PriorFleetRelation, off_mode_prior_relation
from api.compute.scope import WILDCARD, ComputeScope, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import GameSettings, TurnInfo


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


def _off_mode_prior_resolution(
    fleet_services: FleetComputeServices,
    *,
    game_id: str,
    perspective: int,
    player_id: int,
    turn_number: int,
    turn: TurnInfo,
    prior_turn: TurnInfo | None,
    prior_persisted: PersistedFleetLedger | None,
    prior_export_scope: ExportScope,
) -> PriorTurnFleetTorpResolution:
    """Scores overlay while Backfill earlier turns is off.

    When ``off_mode_prior_relation`` is on the mark, that stored ledger is the
    overlay. A hop, a stop, a missing ledger, or a turn that is not stored
    stays pending and is not ensured.
    """
    if prior_persisted is None or prior_turn is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="pending")
    mark = fleet_services.persistence.evidence_mark(game_id, perspective, player_id)
    relation = off_mode_prior_relation(
        turn_number=turn_number,
        settings=turn.settings,
        load_prior_turn=lambda: prior_turn,
        prior_ledger=prior_persisted,
        mark=mark,
    )
    if relation is not PriorFleetRelation.ON_MARK:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="pending")
    return _resolution_from_persisted_fleet(
        prior_persisted,
        prior_export_scope,
        prior_turn=prior_turn,
    )


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
    backfill_earlier_turns: bool,
) -> PriorTurnFleetTorpResolution:
    """Resolve prior-turn fleet torp overlay for scores wire build and ensure admit.

    Prefers an ensure-final DepOutputs / disk ledger via
    ``resolve_fleet_prior_persisted``. While Backfill earlier turns is on, a
    readable non-final prior is not the scores overlay. While it is off, an
    approximate ledger on the current mark is the prior, and a missing earlier
    turn is not ensured.
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

    fleet_services = lookup_fleet_compute_services(ctx)

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
    # An ensure-final prior is the overlay in either mode. The resolved
    # backfill choice does not change that overlay.
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
    # Missing fleet services cannot read the evidence mark. Keep the overlay
    # path so a provenance-final ledger is not admitted, and so a missing prior
    # stays unavailable.
    if fleet_services is not None and not backfill_earlier_turns:
        return _off_mode_prior_resolution(
            fleet_services,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
            turn_number=turn_number,
            turn=turn,
            prior_turn=prior_turn,
            prior_persisted=prior_persisted,
            prior_export_scope=prior_export_scope,
        )

    return resolve_prior_turn_fleet_torp_overlay(
        turn=turn,
        player_id=player_id,
        load_turn=ctx.load_turn,
        query_context=ctx,
        ensure=overlay_ensure,
    )
