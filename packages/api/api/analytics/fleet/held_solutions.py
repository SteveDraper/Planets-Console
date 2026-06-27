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
from api.analytics.scores.host_turn_export import scores_scoreboard_turn_for_placeholder_refine
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.models.game import TurnInfo


@dataclass(frozen=True)
class FleetHeldInference:
    """Resolved scores held solutions for one player on one scoreboard turn."""

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

    def held_inference_for_scoreboard_turn(
        self,
        *,
        game_id: int,
        perspective: int,
        scoreboard_turn: int,
        player_id: int,
        turn: TurnInfo,
        load_turn,
    ) -> FleetHeldInference:
        if self.scores_services.persistence is None:
            return FleetHeldInference(search_status="not_started", solutions=())

        query_turn = load_turn(scoreboard_turn)
        if query_turn is None:
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
            turn=scoreboard_turn,
            player_id=player_id,
        )
        resolved = held_scores_for_scope(ctx, scope, turn=query_turn)
        payload = resolved.payload
        return FleetHeldInference(
            search_status=resolved.decision.search_status,
            solutions=tuple(payload.solutions),
        )

    def held_inference_for_placeholder(
        self,
        *,
        game_id: int,
        perspective: int,
        shell_turn: int,
        built_turn: int,
        player_id: int,
        turn: TurnInfo,
        load_turn,
    ) -> FleetHeldInference:
        scoreboard_turn = scores_scoreboard_turn_for_placeholder_refine(
            built_turn=built_turn,
            shell_turn=shell_turn,
        )
        return self.held_inference_for_scoreboard_turn(
            game_id=game_id,
            perspective=perspective,
            scoreboard_turn=scoreboard_turn,
            player_id=player_id,
            turn=turn,
            load_turn=load_turn,
        )
