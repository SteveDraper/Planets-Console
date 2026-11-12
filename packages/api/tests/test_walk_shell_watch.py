"""The live walk shell projection and the walk watch built on it."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import (
    get_fleet_table_stream_registry,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.on_walk_live import _live_shells
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.analytics.walk_shell_watch import (
    WALK_SHELL_STREAM_WATCH,
    live_walk_shell_keys,
    live_walk_shells,
)
from api.compute.priority_band import WatchedShellKey
from api.models.enums import PlayerStatus
from api.streaming.table_stream.registry import TableStreamRegistry
from api.streaming.table_stream.registry_bootstrap import (
    ensure_table_stream_registries_registered,
)
from api.streaming.table_stream.registry_catalog import (
    register_table_stream_registry,
    reset_table_stream_registry_catalog_for_tests,
)

from tests.export_chain_test_fixtures import enable_backfill_earlier_turns
from tests.off_mode_catch_up_helpers import context_at_turn
from tests.on_walk_live_helpers import attach_stream
from tests.scores_exports_helpers import first_player_id
from tests.test_fleet_eliminated_player import _stamp_player

READ_TIMEOUT_SECONDS = 5.0
HOMEWORLD_ANALYTIC_ID = "homeworld-locator"


@dataclass(frozen=True)
class _WildcardPerspectiveScope:
    game_id: int
    perspective: object
    turn_number: int


@pytest.fixture(autouse=True)
def _empty_stream_registries() -> Iterator[None]:
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()
    yield
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()


@pytest.fixture
def homeworld_registry() -> Iterator[TableStreamRegistry]:
    registry = TableStreamRegistry()
    register_table_stream_registry(HOMEWORLD_ANALYTIC_ID, registry)
    yield registry
    reset_table_stream_registry_catalog_for_tests()
    ensure_table_stream_registries_registered()


def _key(turn: int, player_id: int, *, game_id: int = 10, perspective: int = 2) -> WatchedShellKey:
    return WatchedShellKey(game_id=game_id, perspective=perspective, turn=turn, player_id=player_id)


def test_each_player_on_each_live_walk_stream_is_one_shell():
    attach_stream(
        get_fleet_table_stream_registry(), FleetTableStreamScope(10, 2, 8), None, None, [1, 2]
    )
    attach_stream(
        get_inference_table_stream_registry(), InferenceStreamScope(10, 2, 8), None, None, [1, 2]
    )
    attach_stream(
        get_inference_table_stream_registry(), InferenceStreamScope(11, 3, 5), None, None, [4]
    )

    shells = {(shell.stream.analytic_id, shell.key) for shell in live_walk_shells()}

    assert shells == {
        (FLEET_ANALYTIC_ID, _key(8, 1)),
        (FLEET_ANALYTIC_ID, _key(8, 2)),
        (SCORES_ANALYTIC_ID, _key(8, 1)),
        (SCORES_ANALYTIC_ID, _key(8, 2)),
        (SCORES_ANALYTIC_ID, _key(5, 4, game_id=11, perspective=3)),
    }
    assert live_walk_shell_keys() == frozenset(
        {_key(8, 1), _key(8, 2), _key(5, 4, game_id=11, perspective=3)}
    )
    assert WALK_SHELL_STREAM_WATCH.watched_keys() == live_walk_shell_keys()


def test_a_homeworld_stream_is_not_a_walk_shell(homeworld_registry):
    attach_stream(homeworld_registry, FleetTableStreamScope(10, 2, 8), None, None, [1])
    attach_stream(
        get_fleet_table_stream_registry(), FleetTableStreamScope(10, 2, 9), None, None, [1]
    )

    assert live_walk_shell_keys() == frozenset({_key(9, 1)})


def test_a_stream_whose_perspective_is_not_an_int_has_no_shell():
    attach_stream(
        get_fleet_table_stream_registry(),
        _WildcardPerspectiveScope(game_id=10, perspective="*", turn_number=8),
        None,
        None,
        [1],
    )

    assert live_walk_shells() == ()


def test_a_closed_stream_is_no_longer_watched():
    attach_stream(
        get_fleet_table_stream_registry(), FleetTableStreamScope(10, 2, 8), None, None, [1]
    )
    assert WALK_SHELL_STREAM_WATCH.watched_keys() == frozenset({_key(8, 1)})

    reset_fleet_table_stream_registry_for_tests()

    assert WALK_SHELL_STREAM_WATCH.watched_keys() == frozenset()


def test_a_player_eliminated_on_the_shell_turn_is_watched_but_not_submitted(sample_turn):
    shell_turn = 10
    eliminated = first_player_id(sample_turn)
    stamped = _stamp_player(
        sample_turn,
        eliminated,
        status=int(PlayerStatus.ELIMINATED),
        statusturn=shell_turn,
        turn_number=shell_turn,
    )
    host, ctx = context_at_turn(stamped, shell_turn)
    enable_backfill_earlier_turns(ctx)
    attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(ctx.game_id, ctx.perspective, shell_turn),
        host,
        ctx,
        [eliminated],
    )

    assert live_walk_shell_keys() == frozenset(
        {_key(shell_turn, eliminated, game_id=ctx.game_id, perspective=ctx.perspective)}
    )
    assert _live_shells(ctx.game_id) == []


def test_the_watch_reads_while_writers_hold_the_registry_locks():
    attach_stream(
        get_fleet_table_stream_registry(), FleetTableStreamScope(10, 2, 8), None, None, [1]
    )
    read = threading.Event()
    keys: list[frozenset[WatchedShellKey]] = []

    def read_watch() -> None:
        keys.append(WALK_SHELL_STREAM_WATCH.watched_keys())
        read.set()

    with get_fleet_table_stream_registry()._lock, get_inference_table_stream_registry()._lock:
        threading.Thread(target=read_watch, daemon=True).start()
        assert read.wait(READ_TIMEOUT_SECONDS)

    assert keys == [frozenset({_key(8, 1)})]
