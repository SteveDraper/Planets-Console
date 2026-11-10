"""Shared fleet/scoreboard shell-submit helpers for the on-walk test modules."""

from __future__ import annotations

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.compute.orchestrator import ComputeOrchestrator, ComputeRequest
from api.compute.scope import ComputeScope

from tests.off_mode_catch_up_helpers import FLEET_SCORES_REGISTRY


def fleet_persistence(ctx):
    return ctx.export_services[FLEET_ANALYTIC_ID].persistence


def _hold_pool(*_args, **_kwargs) -> None:
    return None


def held_pool_orchestrator() -> ComputeOrchestrator:
    return ComputeOrchestrator(
        compute_registry=FLEET_SCORES_REGISTRY,
        pool_submitter=_hold_pool,
    )


def shell_scope(ctx, analytic_id: str, turn: int, player_id: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=analytic_id,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=turn,
        player_id=player_id,
    )


def submit_shell(
    ctx,
    analytic_id: str,
    turn: int,
    player_id: int,
    *,
    orchestrator: ComputeOrchestrator | None = None,
) -> ComputeOrchestrator:
    """Production shell submit: no entry step, so the root is not forced."""
    owner = orchestrator if orchestrator is not None else held_pool_orchestrator()
    owner.submit(ComputeRequest(scope=shell_scope(ctx, analytic_id, turn, player_id), ctx=ctx))
    return owner


def accept_shell(ctx, analytic_id: str, turn: int, player_id: int) -> None:
    submit_shell(ctx, analytic_id, turn, player_id)
