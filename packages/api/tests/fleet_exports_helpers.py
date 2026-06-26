"""Shared fixtures and helpers for fleet export tests."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.exports import EXPORT_CATALOG
from api.analytics.fleet.held_solutions import FleetInferenceSupport
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_services import ScoresExportContext
from api.services.inference_row_persistence_service import InferenceRowPersistenceService

from tests.scores_exports_helpers import (
    GAME_ID,
    first_player_id,
    perspective,
)


def fleet_query_context(
    sample_turn,
    *,
    persistence: InferenceRowPersistenceService | None = None,
    scheduler: InferenceRowScheduler | None = None,
    stored_turns: dict[int, object] | None = None,
):
    turns = stored_turns or {sample_turn.settings.turn: sample_turn}

    def load_turn(turn_number: int):
        return turns.get(turn_number)

    scores_services = ScoresExportContext(persistence=persistence)
    if scheduler is not None:
        scores_services = ScoresExportContext(
            persistence=persistence,
            scheduler=scheduler,
        )

    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        stored_turns=turns,
        inference=FleetInferenceSupport(scores_services=scores_services),
    )

    return make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={
            "scores": scores_services,
            "fleet": fleet_services,
        },
    )


def materialize_fleet_tree(ctx, player_id: int, *, turn: int | None = None):
    scope = ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=turn if turn is not None else ctx.ambient_turn,
        player_id=player_id,
    )
    return EXPORT_CATALOG.materialize_export_tree(ctx, scope), scope


def turn_with_score_delta(
    sample_turn,
    *,
    turn_number: int,
    owner_id: int | None = None,
    shipchange: int = 0,
    freighterchange: int = 0,
):
    player_id = owner_id if owner_id is not None else first_player_id(sample_turn)
    turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=turn_number),
        game=replace(sample_turn.game, turn=turn_number),
        ships=[],
    )
    score = replace(
        turn.scores[0],
        turn=turn_number,
        ownerid=player_id,
        shipchange=shipchange,
        freighterchange=freighterchange,
    )
    return replace(turn, scores=[score])
