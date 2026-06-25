"""Load scores held solutions for fleet inference ingest."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_precedence import SearchStatus
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.exports import held_scores_for_scope
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.models.game import TurnInfo


@dataclass(frozen=True)
class FleetHeldInference:
    """Resolved scores held solutions for one player on one host turn."""

    search_status: SearchStatus
    solutions: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class FleetInferenceMaterialization:
    """Scores inference refinement inputs; load_turn is required for held-solution lookup."""

    inference: FleetInferenceSupport
    load_turn: Callable[[int], TurnInfo | None]


@dataclass(frozen=True)
class FleetInferenceSupport:
    """Read-only scores inference access for fleet materialization."""

    scores_services: ScoresExportContext

    def held_inference_for_player(
        self,
        *,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
        turn: TurnInfo,
        load_turn,
    ) -> FleetHeldInference:
        if self.scores_services.persistence is None:
            return FleetHeldInference(search_status="not_started", solutions=())

        ctx = make_analytic_query_context(
            turn,
            TurnAnalyticsOptions(),
            load_turn=load_turn,
            export_services={SCORES_ANALYTIC_ID: self.scores_services},
        )
        scope = ExportScope(
            game_id=game_id,
            perspective=perspective,
            turn=host_turn,
            player_id=player_id,
        )
        resolved = held_scores_for_scope(ctx, scope, turn=turn)
        return FleetHeldInference(
            search_status=resolved.decision.search_status,
            solutions=tuple(resolved.payload.solutions),
        )
