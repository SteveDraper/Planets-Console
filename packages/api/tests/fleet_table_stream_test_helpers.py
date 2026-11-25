"""Query contexts for fleet table-stream tests built from existing fleet services."""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.fleet import ANALYTIC_ID
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.models.game import TurnInfo

from tests.export_chain_test_fixtures import scores_export_context


def query_context_for_fleet_services(
    fleet_services: FleetComputeServices,
    *,
    host_turn: TurnInfo,
) -> AnalyticQueryContext:
    """Build a query context from existing fleet services.

    Does not invent a login-backed ``ensure_turn``. Production admit receives
    the factory ctx from ``TurnAnalyticService``. Services with no inference
    materialization get a scores bundle on a fresh memory backend.
    """
    export_services: dict[str, object] = {ANALYTIC_ID: fleet_services}
    if fleet_services.inference_materialization is not None:
        scores_services = fleet_services.inference_materialization.inference.scores_services
    else:
        scores_services = scores_export_context()
    export_services[SCORES_ANALYTIC_ID] = scores_services
    return make_analytic_query_context(
        host_turn,
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services=export_services,
        game_id=fleet_services.game_id,
        perspective=fleet_services.perspective,
        read_backfill_earlier_turns=fleet_services.persistence.backfill_earlier_turns_enabled,
    )
