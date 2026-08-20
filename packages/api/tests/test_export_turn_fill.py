"""Unit tests for the shared contiguous-turn fill helper used by ensure chains."""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.analytics.export_turn_fill import (
    fill_missing_dependency_chain_turns,
    missing_dependency_chain_turns,
)
from api.analytics.export_types import ExportScope
from api.models.game import TurnInfo

from tests.fixtures.export_framework.harness import (
    build_stored_turn_chain,
    clone_turn_at,
    first_player_id,
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


def _fleet_prepare_context(turns: dict[int, TurnInfo]):
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
    from api.analytics.options import TurnAnalyticsOptions

    shell = turns[max(turns)]
    services = build_ephemeral_fleet_compute_services(
        shell,
        stored_turns=turns,
        game_id=shell.game.id,
        perspective=shell.player.id,
    )
    return make_analytic_query_context(
        shell,
        TurnAnalyticsOptions(),
        game_id=shell.game.id,
        perspective=shell.player.id,
        load_turn=turns.get,
        export_services={"fleet": services},
    )


def _fleet_scope(ctx, turn: int, player_id: int) -> ExportScope:
    return ExportScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=turn,
        player_id=player_id,
    )


def test_prepare_fetches_holes_then_fleet_walk_succeeds(sample_turn):
    from api.analytics.export_turn_fill import prepare_dependency_chain_turns
    from api.compute.dag import plan_compute_dag
    from api.compute.registry import COMPUTE_REGISTRY

    turns = {1: clone_turn_at(sample_turn, 1), 3: clone_turn_at(sample_turn, 3)}
    player_id = first_player_id(sample_turn)
    requested: list[int] = []

    def ensure_turn(turn_number: int) -> TurnInfo | None:
        requested.append(turn_number)
        turns[turn_number] = clone_turn_at(sample_turn, turn_number)
        return turns[turn_number]

    ctx = _fleet_prepare_context(turns)
    ctx.ensure_turn = ensure_turn
    prepare_dependency_chain_turns(
        ctx,
        "fleet",
        _fleet_scope(ctx, 3, player_id),
    )

    assert requested == [2]
    planned = plan_compute_dag(
        ctx,
        "fleet",
        _fleet_scope(ctx, 3, player_id),
        compute_registry=COMPUTE_REGISTRY,
        force_root=True,
    )
    assert planned


def test_prepare_raises_when_login_hook_is_missing(sample_turn):
    from api.analytics.export_turn_fill import (
        DependencyChainFillError,
        prepare_dependency_chain_turns,
    )

    turns = {1: clone_turn_at(sample_turn, 1), 3: clone_turn_at(sample_turn, 3)}
    ctx = _fleet_prepare_context(turns)

    with pytest.raises(DependencyChainFillError, match="sign in to auto-fetch"):
        prepare_dependency_chain_turns(
            ctx,
            "fleet",
            _fleet_scope(ctx, 3, first_player_id(sample_turn)),
        )


def test_prepare_uses_ctx_ensure_turn_when_argument_omitted(sample_turn):
    from api.analytics.export_turn_fill import prepare_dependency_chain_turns

    turns = {1: clone_turn_at(sample_turn, 1), 3: clone_turn_at(sample_turn, 3)}
    requested: list[int] = []

    def ensure_turn(turn_number: int) -> TurnInfo | None:
        requested.append(turn_number)
        turns[turn_number] = clone_turn_at(sample_turn, turn_number)
        return turns[turn_number]

    ctx = _fleet_prepare_context(turns)
    ctx.ensure_turn = ensure_turn
    prepare_dependency_chain_turns(ctx, "fleet", _fleet_scope(ctx, 3, first_player_id(sample_turn)))
    assert requested == [2]


def test_plan_compute_dag_raises_validation_error_when_hole_remains(sample_turn):
    from api.compute.dag import plan_compute_dag
    from api.compute.registry import COMPUTE_REGISTRY
    from api.errors import ValidationError

    turns = {1: clone_turn_at(sample_turn, 1), 3: clone_turn_at(sample_turn, 3)}
    ctx = _fleet_prepare_context(turns)

    with pytest.raises(ValidationError, match="missing turn 2"):
        plan_compute_dag(
            ctx,
            "fleet",
            _fleet_scope(ctx, 3, first_player_id(sample_turn)),
            compute_registry=COMPUTE_REGISTRY,
            force_root=True,
        )


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
