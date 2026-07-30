"""Unit tests for the shared contiguous-turn fill helper used by ensure chains."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.export_turn_fill import (
    fill_missing_dependency_chain_turns,
    missing_dependency_chain_turns,
)
from api.analytics.export_types import ExportScope
from api.models.game import TurnInfo

from tests.fixtures.export_framework.harness import (
    build_stored_turn_chain,
    clone_turn_at,
    make_fixture_query_context,
)


def _scope(ctx, turn: int) -> ExportScope:
    return ExportScope(game_id=ctx.game_id, perspective=ctx.perspective, turn=turn)


def test_fill_reports_contiguous_chain_without_fetching(sample_turn):
    turns = build_stored_turn_chain(sample_turn, through_turn=3)
    ctx = make_fixture_query_context(turns[3], stored_turns=turns)
    fetched: list[int] = []

    fill = fill_missing_dependency_chain_turns(
        ctx,
        _scope(ctx, 3),
        ensure_turn=lambda turn_number: fetched.append(turn_number) or turns.get(turn_number),
    )

    assert fill.still_missing is None
    assert fill.fetched_turns == ()
    assert fill.auto_fetch_unavailable is False
    assert fetched == []


def test_fill_reports_first_hole_without_ensure_turn_hook(sample_turn):
    turns = {1: clone_turn_at(sample_turn, 1), 3: clone_turn_at(sample_turn, 3)}
    ctx = make_fixture_query_context(turns[3], stored_turns=turns)

    fill = fill_missing_dependency_chain_turns(ctx, _scope(ctx, 3), ensure_turn=None)

    assert fill.still_missing == 2
    assert fill.auto_fetch_unavailable is True
    assert fill.fetched_turns == ()


def test_fill_fetches_every_hole_below_the_scope_turn(sample_turn):
    turns = {1: clone_turn_at(sample_turn, 1), 4: clone_turn_at(sample_turn, 4)}
    ctx = make_fixture_query_context(turns[4], stored_turns=turns)
    requested: list[int] = []

    def ensure_turn(turn_number: int) -> TurnInfo | None:
        requested.append(turn_number)
        turns[turn_number] = clone_turn_at(sample_turn, turn_number)
        return turns[turn_number]

    fill = fill_missing_dependency_chain_turns(ctx, _scope(ctx, 4), ensure_turn=ensure_turn)

    assert requested == [2, 3]
    assert fill.fetched_turns == (2, 3)
    assert fill.still_missing is None
    assert fill.auto_fetch_unavailable is False


def test_fill_stops_at_the_first_fetch_failure(sample_turn):
    turns = {1: clone_turn_at(sample_turn, 1), 5: clone_turn_at(sample_turn, 5)}
    ctx = make_fixture_query_context(turns[5], stored_turns=turns)
    requested: list[int] = []

    def ensure_turn(turn_number: int) -> TurnInfo | None:
        requested.append(turn_number)
        if turn_number != 2:
            return None
        turns[turn_number] = clone_turn_at(sample_turn, turn_number)
        return turns[turn_number]

    fill = fill_missing_dependency_chain_turns(ctx, _scope(ctx, 5), ensure_turn=ensure_turn)

    assert requested == [2, 3]
    assert fill.fetched_turns == (2,)
    assert fill.still_missing == 3
    assert fill.auto_fetch_unavailable is False


def test_missing_turns_start_at_the_accelerated_ensure_floor(sample_turn):
    accelerated = replace(
        clone_turn_at(sample_turn, 5),
        settings=replace(sample_turn.settings, turn=5, acceleratedturns=4),
    )
    turns = {
        4: replace(accelerated, settings=replace(accelerated.settings, turn=4)),
        5: accelerated,
    }
    ctx = make_fixture_query_context(accelerated, stored_turns=turns)

    assert missing_dependency_chain_turns(ctx, _scope(ctx, 5)) == ()
