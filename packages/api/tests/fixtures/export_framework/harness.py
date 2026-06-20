"""Test harness for export framework fixture analytics."""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.exports.registry import merge_export_registry
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import TurnInfo
from tests.fixtures.export_framework.alpha_exports import EXPORT_CATALOG as ALPHA_EXPORT_CATALOG
from tests.fixtures.export_framework.beta_exports import EXPORT_CATALOG as BETA_EXPORT_CATALOG
from tests.fixtures.export_framework.cycle_exports import (
    CYCLE_A_EXPORT_CATALOG,
    CYCLE_B_EXPORT_CATALOG,
)
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE

FIXTURE_EXPORT_REGISTRY = merge_export_registry(ALPHA_EXPORT_CATALOG, BETA_EXPORT_CATALOG)
CYCLE_FIXTURE_EXPORT_REGISTRY = merge_export_registry(
    CYCLE_A_EXPORT_CATALOG,
    CYCLE_B_EXPORT_CATALOG,
)


def make_fixture_query_context(
    turn: TurnInfo,
    *,
    stored_turns: dict[int, TurnInfo] | None = None,
    enforce_inline_ensure_threshold: bool = True,
) -> AnalyticQueryContext:
    """Build a query context with fixture catalogs and optional stored-turn map."""
    FIXTURE_EXPORT_STATE.reset()
    turns = stored_turns or {turn.settings.turn: turn}

    def load_turn(turn_number: int) -> TurnInfo | None:
        return turns.get(turn_number)

    return make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_registry=FIXTURE_EXPORT_REGISTRY,
        enforce_inline_ensure_threshold=enforce_inline_ensure_threshold,
    )


def make_cycle_fixture_query_context(
    turn: TurnInfo,
    *,
    stored_turns: dict[int, TurnInfo] | None = None,
    enforce_inline_ensure_threshold: bool = True,
) -> AnalyticQueryContext:
    """Build a query context with cyclic ensure-dependency fixture catalogs."""
    FIXTURE_EXPORT_STATE.reset()
    turns = stored_turns or {turn.settings.turn: turn}

    def load_turn(turn_number: int) -> TurnInfo | None:
        return turns.get(turn_number)

    return make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_registry=CYCLE_FIXTURE_EXPORT_REGISTRY,
        enforce_inline_ensure_threshold=enforce_inline_ensure_threshold,
    )


def clone_turn_at(turn: TurnInfo, turn_number: int) -> TurnInfo:
    """Shallow clone with a different settings.turn for multi-turn fixture chains."""
    from dataclasses import replace

    settings = replace(turn.settings, turn=turn_number)
    game = replace(turn.game, turn=turn_number)
    return replace(turn, settings=settings, game=game)


def build_stored_turn_chain(
    base_turn: TurnInfo,
    *,
    through_turn: int,
) -> dict[int, TurnInfo]:
    return {
        turn_number: clone_turn_at(base_turn, turn_number)
        for turn_number in range(1, through_turn + 1)
    }


def first_player_id(turn: TurnInfo) -> int:
    if turn.scores:
        return turn.scores[0].ownerid
    return turn.player.id
