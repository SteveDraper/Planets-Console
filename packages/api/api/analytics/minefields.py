"""Core Minefields map analytic: known-field facts with pre/post-decay radii."""

from __future__ import annotations

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.concepts.minefield_decay import (
    radius_from_units,
    remaining_units_after_known_decay,
)
from api.models.game import TurnInfo
from api.models.space import Minefield, Nebula

ANALYTIC_ID = "minefields"


def _field_to_wire(field: Minefield, nebulas: list[Nebula]) -> dict:
    remaining = remaining_units_after_known_decay(field.units, field.x, field.y, nebulas)
    return {
        "id": field.id,
        "ownerId": field.ownerid,
        "isWeb": field.isweb,
        "isHidden": field.ishidden,
        "x": field.x,
        "y": field.y,
        "units": field.units,
        "infoTurn": field.infoturn,
        "friendlyCode": field.friendlycode,
        "preRadius": radius_from_units(field.units),
        "postRadius": radius_from_units(remaining),
    }


def compute_minefields_map(ctx: AnalyticComputeContext) -> dict:
    """Return known minefield facts for the shell turn (no hover copy)."""
    turn = ctx.turn
    fields = [_field_to_wire(field, turn.nebulas) for field in turn.minefields if field.units > 0]
    return {
        "analyticId": ANALYTIC_ID,
        "minefields": fields,
        "nodes": [],
        "edges": [],
    }


def get_minefields_map(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
) -> dict:
    """Convenience entry for tests and direct callers."""
    return invoke_analytic_compute(
        compute_minefields_map,
        turn,
        options,
        game_id=turn.game.id,
        perspective=turn.player.id,
    )


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_minefields_map,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)
