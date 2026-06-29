"""Production consumer for prior-turn fleet composition feeding scores inference (#133)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

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

logger = logging.getLogger(__name__)

FleetTorpInputStatus = Literal["not_applicable", "pending", "applied", "unavailable"]


@dataclass(frozen=True)
class PriorTurnFleetTorpResolution:
    """Prior-turn fleet torp overlay plus provenance for inference diagnostics."""

    overlay: FleetTorpOverlay | None
    input_status: FleetTorpInputStatus


_FLEET_TORP_INPUT_STATUSES: frozenset[str] = frozenset(
    {"not_applicable", "pending", "applied", "unavailable"}
)


def fleet_torp_input_status_diagnostics(
    input_status: FleetTorpInputStatus | None,
) -> dict[str, object]:
    if input_status is None:
        return {}
    return {"fleetTorpInputStatus": input_status}


def fleet_torp_complete_wire_fields_from_diagnostics(
    diagnostics: dict[str, object] | None,
) -> tuple[FleetTorpInputStatus | None, list[int] | None]:
    """Promote fleet torp functional fields out of diagnostics for wire payloads."""
    if not diagnostics:
        return None, None

    input_status: FleetTorpInputStatus | None = None
    status_raw = diagnostics.get("fleetTorpInputStatus")
    if isinstance(status_raw, str) and status_raw in _FLEET_TORP_INPUT_STATUSES:
        input_status = status_raw  # type: ignore[assignment]

    belief_set_torp_ids: list[int] | None = None
    overlay = diagnostics.get("fleetTorpOverlay")
    if isinstance(overlay, dict):
        ids_raw = overlay.get("beliefSetTorpIds")
        if isinstance(ids_raw, list):
            belief_set_torp_ids = [torp_id for torp_id in ids_raw if isinstance(torp_id, int)]

    return input_status, belief_set_torp_ids


def _resolve_fleet_services(
    *,
    query_context: AnalyticQueryContext | None,
    export_services: Mapping[str, object] | None,
):
    from api.analytics.export_context import export_service_for
    from api.analytics.fleet.compute_services import FleetComputeServices

    if query_context is not None:
        services = export_service_for(query_context, FLEET_ANALYTIC_ID, FleetComputeServices)
        if services is not None:
            return services
        injected = query_context.export_services.get(FLEET_ANALYTIC_ID)
        if isinstance(injected, FleetComputeServices):
            return injected
        return None
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
) -> PriorTurnFleetTorpResolution:
    """Load belief-set torp overlay from fleet export at host turn minus one.

    Returns overlay plus ``input_status`` for inference diagnostics. Callers
    treat ``overlay is None`` as an empty belief set via
    ``effective_fleet_torp_overlay``.

    When ``ensure`` is false, reads only persisted fleet snapshots and does not
    run export ensure (for inference table-stream scheduling).
    """
    host_turn = turn.settings.turn
    if host_turn <= 1:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="not_applicable")

    fleet_services = _resolve_fleet_services(
        query_context=query_context,
        export_services=export_services,
    )
    if fleet_services is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="unavailable")

    prior_turn = host_turn - 1
    prior_turn_info = load_turn(prior_turn)
    if prior_turn_info is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="pending")

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
        return PriorTurnFleetTorpResolution(overlay=None, input_status="pending")

    return PriorTurnFleetTorpResolution(
        overlay=_overlay_from_snapshot(snapshot, scope),
        input_status="applied",
    )


def schedule_background_prior_turn_fleet_warm(
    *,
    turn: TurnInfo,
    load_turn: Callable[[int], TurnInfo | None],
    export_services: Mapping[str, object] | None,
) -> None:
    """Kick off non-blocking materialization of fleet@(host_turn - 1) for table streams."""
    host_turn = turn.settings.turn
    if host_turn <= 1:
        return

    fleet_services = _resolve_fleet_services(
        query_context=None,
        export_services=export_services,
    )
    if fleet_services is None:
        return

    prior_turn = host_turn - 1
    prior_turn_info = load_turn(prior_turn)
    if prior_turn_info is None:
        return

    if fleet_services.persistence.has_snapshot(
        fleet_services.game_id,
        fleet_services.perspective,
        prior_turn,
    ):
        return

    def warm_prior_turn_fleet() -> None:
        from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
        from api.errors import ConflictError

        persistence = fleet_services.persistence
        game_id = fleet_services.game_id
        perspective = fleet_services.perspective

        def prior_turn_snapshot_available() -> bool:
            return persistence.has_snapshot(game_id, perspective, prior_turn)

        try:
            get_or_materialize_fleet_snapshot(
                persistence,
                game_id,
                perspective,
                prior_turn_info,
                load_turn=fleet_services.load_turn,
                inference_materialization=fleet_services.inference_materialization,
            )
        except ConflictError, OSError, ValueError, KeyError:
            if prior_turn_snapshot_available():
                return
            logger.warning(
                "Background prior-turn fleet warm failed for game %s perspective %s turn %s",
                game_id,
                perspective,
                prior_turn,
            )

    threading.Thread(target=warm_prior_turn_fleet, daemon=True).start()
