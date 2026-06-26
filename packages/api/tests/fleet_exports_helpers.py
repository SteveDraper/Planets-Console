"""Shared fixtures and helpers for fleet export tests."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.export_types import ExportScope
from api.analytics.fleet.exports import EXPORT_CATALOG

from tests.scores_exports_helpers import first_player_id


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
