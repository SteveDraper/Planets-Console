"""Production consumer for prior-turn fleet composition feeding scores inference (#133)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.export_scope import ledgers_for_scope
from api.analytics.fleet.max_tech import max_tech_by_axis_from_fleet_records
from api.analytics.fleet.types import FleetShipRecord, FleetTurnSnapshot
from api.analytics.military_score_inference.fleet_torp_overlay import (
    FleetTorpOverlay,
    overlay_from_fleet_records,
)
from api.analytics.military_score_inference.tier_policy import resolve_fleet_inference_tuning
from api.analytics.options import TurnAnalyticsOptions
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext

FleetTorpInputStatus = Literal["not_applicable", "pending", "applied", "unavailable"]


@dataclass(frozen=True)
class PriorTurnFleetTorpResolution:
    """Prior-turn fleet torp overlay plus provenance for inference diagnostics.

    When ``input_status`` is ``applied``, ``max_tech_by_axis`` holds per-axis max
    catalog techlevels observed on the prior fleet (keys ``hulls``/``engines``/
    ``beams``/``launchers``; axes with no evidence omitted). Otherwise the mapping
    is empty and early tech gates keep their YAML constants (#227).
    """

    overlay: FleetTorpOverlay | None
    input_status: FleetTorpInputStatus
    max_tech_by_axis: dict[str, int] = field(default_factory=dict)

    def prior_fleet_max_tech_for_admission(self) -> dict[str, int] | None:
        """Prior-fleet max tech for early inference gates, or ``None`` when not applied.

        Callers that admit prior-fleet tech into inference must use this helper
        rather than re-encoding the ``input_status == "applied"`` gate.
        """
        if self.input_status != "applied":
            return None
        return dict(self.max_tech_by_axis)


def records_for_scope(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
) -> list[FleetShipRecord]:
    records: list[FleetShipRecord] = []
    for ledger in ledgers_for_scope(snapshot, scope):
        records.extend(ledger.records)
    return records


def resolution_from_fleet_records(
    records: list[FleetShipRecord],
    *,
    prior_turn: TurnInfo,
    input_status: FleetTorpInputStatus = "applied",
    option_set_mass_threshold: float | None = None,
) -> PriorTurnFleetTorpResolution:
    threshold = (
        resolve_fleet_inference_tuning().option_set_mass_threshold
        if option_set_mass_threshold is None
        else option_set_mass_threshold
    )
    return PriorTurnFleetTorpResolution(
        overlay=overlay_from_fleet_records(records),
        input_status=input_status,
        max_tech_by_axis=max_tech_by_axis_from_fleet_records(
            records,
            prior_turn,
            option_set_mass_threshold=threshold,
        ),
    )


_FLEET_TORP_INPUT_STATUSES: frozenset[str] = frozenset(
    {"not_applicable", "pending", "applied", "unavailable"}
)


def fleet_torp_input_status_diagnostics(
    input_status: FleetTorpInputStatus | None,
) -> dict[str, object]:
    if input_status is None:
        return {}
    return {"fleetTorpInputStatus": input_status}


def _validated_fleet_torp_input_status(raw: object | None) -> FleetTorpInputStatus | None:
    if isinstance(raw, str) and raw in _FLEET_TORP_INPUT_STATUSES:
        return raw  # type: ignore[assignment]
    return None


def _filtered_belief_set_torp_ids(raw: object | None) -> list[int] | None:
    if isinstance(raw, list):
        return [torp_id for torp_id in raw if isinstance(torp_id, int)]
    return None


def fleet_torp_complete_wire_fields(
    *,
    diagnostics: dict[str, object] | None,
    fleet_torp_input_status: object | None = None,
    fleet_torp_overlay_belief_set_torp_ids: object | None = None,
) -> tuple[FleetTorpInputStatus | None, list[int] | None]:
    """Promote fleet torp functional fields for wire payloads with shared validation."""
    if fleet_torp_input_status is not None or fleet_torp_overlay_belief_set_torp_ids is not None:
        return (
            _validated_fleet_torp_input_status(fleet_torp_input_status),
            _filtered_belief_set_torp_ids(fleet_torp_overlay_belief_set_torp_ids),
        )

    if not diagnostics:
        return None, None

    input_status = _validated_fleet_torp_input_status(diagnostics.get("fleetTorpInputStatus"))

    belief_set_torp_ids: list[int] | None = None
    overlay = diagnostics.get("fleetTorpOverlay")
    if isinstance(overlay, dict):
        belief_set_torp_ids = _filtered_belief_set_torp_ids(overlay.get("beliefSetTorpIds"))

    return input_status, belief_set_torp_ids


def fleet_torp_complete_wire_fields_from_diagnostics(
    diagnostics: dict[str, object] | None,
) -> tuple[FleetTorpInputStatus | None, list[int] | None]:
    """Promote fleet torp functional fields out of diagnostics for wire payloads."""
    return fleet_torp_complete_wire_fields(diagnostics=diagnostics)


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

    if scope.player_id is None:
        if not persistence.has_snapshot(scope.game_id, scope.perspective, scope.turn):
            return None
        return persistence.get_snapshot(scope.game_id, scope.perspective, scope.turn)

    if not persistence.has_final_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn,
        scope.player_id,
    ):
        return None
    persisted = persistence.get_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn,
        scope.player_id,
    )
    if persisted is None:
        return None
    return FleetTurnSnapshot(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        players=[persisted.ledger],
    )


def _overlay_from_snapshot(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
    *,
    prior_turn: TurnInfo,
) -> PriorTurnFleetTorpResolution:
    return resolution_from_fleet_records(records_for_scope(snapshot, scope), prior_turn=prior_turn)


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
    ``effective_fleet_torp_overlay``. When applied, also returns
    ``max_tech_by_axis`` for early tech-gate admission (#227).

    When ``ensure`` is false, reads only persisted fleet snapshots and does not
    run export ensure (for inference table-stream scheduling).
    """
    host_turn = turn.settings.turn
    prior_turn = host_turn - 1
    if prior_turn < accelerated_ensure_floor(turn.settings, host_turn):
        return PriorTurnFleetTorpResolution(overlay=None, input_status="not_applicable")

    fleet_services = _resolve_fleet_services(
        query_context=query_context,
        export_services=export_services,
    )
    if fleet_services is None:
        return PriorTurnFleetTorpResolution(overlay=None, input_status="unavailable")

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

    return _overlay_from_snapshot(snapshot, scope, prior_turn=prior_turn_info)


def schedule_background_prior_turn_fleet_warm(
    *,
    turn: TurnInfo,
    load_turn: Callable[[int], TurnInfo | None],
    export_services: Mapping[str, object] | None,
    player_ids: tuple[int, ...],
) -> None:
    """Kick off non-blocking per-player materialization of fleet@(host_turn - 1)."""
    host_turn = turn.settings.turn
    prior_turn = host_turn - 1
    if prior_turn < accelerated_ensure_floor(turn.settings, host_turn) or not player_ids:
        return

    fleet_services = _resolve_fleet_services(
        query_context=None,
        export_services=export_services,
    )
    if fleet_services is None:
        return

    prior_turn_info = load_turn(prior_turn)
    if prior_turn_info is None:
        return

    persistence = fleet_services.persistence
    game_id = fleet_services.game_id
    perspective = fleet_services.perspective
    players_needing_warm = tuple(
        player_id
        for player_id in player_ids
        if not persistence.has_final_ledger(game_id, perspective, prior_turn, player_id)
    )
    if not players_needing_warm:
        return

    query_context = make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services=export_services,
    )
    from api.compute.orchestrator import ComputeRequest
    from api.compute.runtime import get_compute_orchestrator
    from api.compute.scope import ComputeScope

    orchestrator = get_compute_orchestrator()
    for player_id in players_needing_warm:
        orchestrator.submit(
            ComputeRequest(
                scope=ComputeScope(
                    analytic_id=FLEET_ANALYTIC_ID,
                    game_id=game_id,
                    perspective=perspective,
                    turn=prior_turn,
                    player_id=player_id,
                ),
                priority_band="background",
                ctx=query_context,
            )
        )
