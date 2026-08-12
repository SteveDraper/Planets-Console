"""Table/map batch compute: fan-out scopes and orchestrator ensure (#202).

``TurnAnalyticService.get_turn_analytics`` is the designated in-process caller.
Pool workers and leaf ``run_step`` must not call these helpers.
"""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.turn_roster import iter_turn_players
from api.compute.orchestrator_state import ComputeRequest
from api.compute.scope import ComputeScope, normalize_export_scope_to_compute_scope
from api.models.game import TurnInfo


def table_map_compute_scopes(
    analytic_id: str,
    ctx: AnalyticQueryContext,
    turn: TurnInfo,
) -> tuple[ComputeScope, ...]:
    """Return the batch compute scopes for one table/map REST request.

    Player-keyed analytics fan out to one scope per roster player. Analytics
    that omit ``player_id`` from the scope key yield a single unscoped node.
    """
    from api.compute.registry import COMPUTE_REGISTRY

    registration = COMPUTE_REGISTRY[analytic_id]
    spec = registration.scope_key_spec
    if "player_id" in spec.axes:
        export_scopes = tuple(
            ExportScope(
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                turn=ctx.ambient_turn,
                player_id=player.id,
            )
            for player in iter_turn_players(turn)
        )
    else:
        export_scopes = (
            ExportScope(
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                turn=ctx.ambient_turn,
                player_id=None,
            ),
        )
    return tuple(
        normalize_export_scope_to_compute_scope(
            export_scope,
            analytic_id=analytic_id,
            scope_key_spec=spec,
        )
        for export_scope in export_scopes
    )


def ensure_table_map_compute(
    ctx: AnalyticQueryContext,
    analytic_id: str,
    turn: TurnInfo,
) -> None:
    """Ensure table/map durable inputs via orchestrator submit-all-then-wait.

    No-op when the analytic has no compute registration, or when its profile
    sets ``route_table_map=False`` (scores REST table is a TurnInfo projection;
    inference is stream-only). Cache hits short-circuit on the inline backend
    via ``PersistencePolicy.is_satisfied``.
    """
    from api.compute.registry import COMPUTE_REGISTRY
    from api.compute.runtime import get_compute_orchestrator

    registration = COMPUTE_REGISTRY.get(analytic_id)
    if registration is None:
        return
    if not registration.compute_profile.route_table_map:
        return

    scopes = table_map_compute_scopes(analytic_id, ctx, turn)
    if not scopes:
        return

    orchestrator = get_compute_orchestrator()
    orchestrator.ensure_scopes(
        tuple(
            ComputeRequest(
                scope=scope,
                ctx=ctx,
                priority_band="interactive_ensure",
            )
            for scope in scopes
        )
    )
