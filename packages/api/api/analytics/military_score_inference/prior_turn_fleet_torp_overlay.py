"""Production consumer for prior-turn fleet composition feeding scores inference (#133)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.export_scope import ledgers_for_scope
from api.analytics.fleet.types import FleetShipRecord, FleetTurnSnapshot
from api.analytics.military_score_inference.fleet_torp_overlay import (
    FleetTorpOverlay,
    launcher_belief_set_from_fleet_records,
)
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext


def _resolve_fleet_services(
    *,
    query_context: AnalyticQueryContext | None,
    export_services: Mapping[str, object] | None,
):
    from api.analytics.fleet.compute_services import FleetComputeServices, resolve_fleet_services

    if query_context is not None:
        return resolve_fleet_services(query_context)
    if export_services is None:
        return None
    fleet_services = export_services.get(FLEET_ANALYTIC_ID)
    if isinstance(fleet_services, FleetComputeServices):
        return fleet_services
    return None


def _load_prior_turn_fleet_snapshot(
    *,
    scope: ExportScope,
    query_context: AnalyticQueryContext | None,
    export_services: Mapping[str, object] | None,
    ensure: bool,
    turn: TurnInfo,
    load_turn: Callable[[int], TurnInfo | None],
) -> FleetTurnSnapshot | None:
    """Load prior-turn fleet snapshot from persistence or via export ensure."""
    fleet_services = _resolve_fleet_services(
        query_context=query_context,
        export_services=export_services,
    )
    if fleet_services is None:
        return None

    persistence = fleet_services.persistence
    if ensure:
        from api.analytics.fleet.exports import ensure_fleet_export

        ctx = query_context
        if ctx is None:
            if export_services is None:
                return None
            ctx = make_analytic_query_context(
                turn,
                TurnAnalyticsOptions(),
                load_turn=load_turn,
                export_services=export_services,
            )
        if not ensure_fleet_export(ctx, scope):
            return None

    if not persistence.has_snapshot(scope.game_id, scope.perspective, scope.turn):
        return None
    return persistence.get_snapshot(scope.game_id, scope.perspective, scope.turn)


def _overlay_from_snapshot(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
) -> FleetTorpOverlay:
    records: list[FleetShipRecord] = []
    for ledger in ledgers_for_scope(snapshot, scope):
        records.extend(ledger.records)
    belief = launcher_belief_set_from_fleet_records(records)
    return FleetTorpOverlay(belief_set=belief)


def resolve_prior_turn_fleet_torp_overlay(
    *,
    turn: TurnInfo,
    player_id: int,
    load_turn: Callable[[int], TurnInfo | None],
    query_context: AnalyticQueryContext | None = None,
    export_services: Mapping[str, object] | None = None,
    ensure: bool = True,
) -> FleetTorpOverlay | None:
    """Load belief-set torp overlay from fleet export at host turn minus one.

    Returns ``None`` when there is no prior turn, the prior turn is not stored,
    fleet export is unavailable, or no export services were supplied. Callers
    treat ``None`` as an empty belief set via ``effective_fleet_torp_overlay``.

    When ``ensure`` is false, reads only persisted fleet snapshots and does not
    run export ensure (for inference table-stream scheduling).
    """
    host_turn = turn.settings.turn
    if host_turn <= 1:
        return None
    prior_turn = host_turn - 1
    prior_turn_info = load_turn(prior_turn)
    if prior_turn_info is None:
        return None

    scope = ExportScope(
        game_id=turn.game.id,
        perspective=turn.player.id,
        turn=prior_turn,
        player_id=player_id,
    )

    snapshot = _load_prior_turn_fleet_snapshot(
        scope=scope,
        query_context=query_context,
        export_services=export_services,
        ensure=ensure,
        turn=turn,
        load_turn=load_turn,
    )
    if snapshot is None:
        return None

    return _overlay_from_snapshot(snapshot, scope)
