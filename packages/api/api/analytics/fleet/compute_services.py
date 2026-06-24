"""Injected services for fleet analytic compute and snapshot chaining."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.export_context import export_service_for
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo
from api.storage.memory_asset import MemoryAssetBackend

ANALYTIC_ID = "fleet"


@dataclass(frozen=True)
class FleetComputeServices:
    persistence: FleetSnapshotPersistenceService
    game_id: int
    perspective: int
    load_turn: Callable[[int], TurnInfo | None]


def turn_chain_through(turn: TurnInfo) -> dict[int, TurnInfo]:
    """Build stored turns 1..T from one shell snapshot (roster-stable chain scaffold)."""
    chain: dict[int, TurnInfo] = {}
    for turn_number in range(1, turn.settings.turn + 1):
        chain[turn_number] = replace(
            turn,
            settings=replace(turn.settings, turn=turn_number),
            game=replace(turn.game, turn=turn_number),
        )
    return chain


def build_ephemeral_fleet_compute_services(
    turn: TurnInfo,
    *,
    game_id: int | None = None,
    perspective: int = 1,
    stored_turns: dict[int, TurnInfo] | None = None,
) -> FleetComputeServices:
    """In-memory fleet services for tests and direct callers; snapshots are not durable."""
    resolved_turns = stored_turns if stored_turns is not None else turn_chain_through(turn)

    def load_turn(turn_number: int) -> TurnInfo | None:
        return resolved_turns.get(turn_number)

    return FleetComputeServices(
        persistence=FleetSnapshotPersistenceService(MemoryAssetBackend(initial={})),
        game_id=game_id if game_id is not None else turn.game.id,
        perspective=perspective,
        load_turn=load_turn,
    )


def resolve_fleet_compute_services(ctx: AnalyticComputeContext) -> FleetComputeServices:
    services = export_service_for(ctx.exports, ANALYTIC_ID, FleetComputeServices)
    if services is not None:
        return services

    injected = ctx.exports.export_services.get(ANALYTIC_ID)
    if injected is None:
        raise RuntimeError(
            f"Fleet compute requires {ANALYTIC_ID!r} in ctx.export_services; "
            "inject FleetComputeServices via TurnAnalyticService or test helpers."
        )
    raise RuntimeError(
        f"Fleet compute export_services[{ANALYTIC_ID!r}] must be FleetComputeServices, "
        f"got {type(injected).__name__}."
    )
