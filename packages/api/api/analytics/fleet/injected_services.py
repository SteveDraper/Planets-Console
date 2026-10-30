"""Fleet compute service bundle and the none-returning context lookup.

Ledger readers import this module. It does not import held solutions, so
resolving services does not load the scores package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.fleet.held_solutions import FleetInferenceMaterialization


@dataclass(frozen=True)
class FleetComputeServices:
    persistence: FleetSnapshotPersistenceService
    game_id: int
    perspective: int
    load_turn: Callable[[int], TurnInfo | None]
    inference_materialization: FleetInferenceMaterialization | None = None


def lookup_fleet_compute_services(ctx: AnalyticQueryContext) -> FleetComputeServices | None:
    """Return fleet compute services when this query context has them."""
    return export_service_for(ctx, ANALYTIC_ID, FleetComputeServices)


def fleet_evidence_generation_for_player(
    ctx: AnalyticQueryContext | None,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
) -> int | None:
    """Current fleet evidence mark, or None when fleet is not on this context.

    None means the caller should omit freshness fields. Zero is a real mark.
    """
    if ctx is None:
        return None
    services = lookup_fleet_compute_services(ctx)
    if services is None:
        return None
    return services.persistence.evidence_mark(game_id, perspective, player_id).evidence_generation
