"""Production consumer for prior-turn fleet composition feeding scores inference (#133)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.composition_export import build_fleet_composition_branch
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.military_score_inference.fleet_torp_overlay import (
    FleetTorpOverlay,
    launcher_belief_set_from_composition,
)
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext

FLEET_COMPOSITION_LAUNCHER_PATH = "$.composition.launcherTypes"


def _launcher_types_from_persisted_fleet(
    export_services: Mapping[str, object],
    *,
    game_id: int,
    perspective: int,
    prior_turn: int,
    player_id: int,
    prior_turn_info: TurnInfo,
) -> dict[str, object] | None:
    """Read launcher histogram from a persisted fleet snapshot without export ensure."""
    from api.analytics.fleet.compute_services import FleetComputeServices

    fleet_services = export_services.get(FLEET_ANALYTIC_ID)
    if not isinstance(fleet_services, FleetComputeServices):
        return None
    persistence = fleet_services.persistence
    if not persistence.has_snapshot(game_id, perspective, prior_turn):
        return None
    snapshot = persistence.get_snapshot(game_id, perspective, prior_turn)
    if snapshot is None:
        return None
    scope = ExportScope(
        game_id=game_id,
        perspective=perspective,
        turn=prior_turn,
        player_id=player_id,
    )
    composition = build_fleet_composition_branch(snapshot, scope, turn=prior_turn_info)
    launcher_types = composition.get("launcherTypes")
    if not isinstance(launcher_types, dict):
        return None
    return launcher_types


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

    launcher_types: dict[str, object] | None = None
    if not ensure and export_services is not None:
        launcher_types = _launcher_types_from_persisted_fleet(
            export_services,
            game_id=turn.game.id,
            perspective=turn.player.id,
            prior_turn=prior_turn,
            player_id=player_id,
            prior_turn_info=prior_turn_info,
        )
    else:
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

        result = ctx.query(
            FLEET_ANALYTIC_ID,
            [FLEET_COMPOSITION_LAUNCHER_PATH],
            scope_overrides={"turn": prior_turn, "player_id": player_id},
        )
        if result.status != "ok":
            return None

        path_result = result.paths.get(FLEET_COMPOSITION_LAUNCHER_PATH)
        if path_result is None or path_result.kind != "value":
            return None

        raw_launcher_types = path_result.value
        if isinstance(raw_launcher_types, dict):
            launcher_types = raw_launcher_types

    if launcher_types is None:
        return None

    belief = launcher_belief_set_from_composition({"launcherTypes": launcher_types})
    return FleetTorpOverlay(belief_set=belief)
