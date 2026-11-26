"""Tests for analytic-agnostic table-stream registry catalog registration."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from api.analytics.fleet.fleet_table_stream_registry import (
    detach_fleet_table_stream,
    get_fleet_table_stream_registry,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
    reset_inference_table_stream_registry_for_tests,
)
from api.streaming.table_stream.registry_bootstrap import (
    ensure_table_stream_registries_registered,
)
from api.streaming.table_stream.registry_catalog import (
    active_table_stream_bindings,
    live_table_streams,
    reset_table_stream_registry_catalog_for_tests,
)
from api.streaming.table_stream.scoped_connect import iter_table_stream_connect_with_scope


def setup_function() -> None:
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()


def teardown_function() -> None:
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()


@pytest.fixture
def empty_catalog() -> Iterator[None]:
    reset_table_stream_registry_catalog_for_tests()
    yield
    reset_table_stream_registry_catalog_for_tests()
    ensure_table_stream_registries_registered()


def _module_imports_name(module_path: Path, name: str) -> bool:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == name or alias.name.startswith(f"{name}.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            if module == name or (module is not None and module.startswith(f"{name}.")):
                return True
            if any(alias.name == name for alias in node.names):
                return True
    return False


def test_fleet_and_scores_registry_modules_do_not_import_registry_catalog() -> None:
    api_root = Path(__file__).resolve().parents[1] / "api"
    fleet_path = api_root / "analytics/fleet/fleet_table_stream_registry.py"
    scores_path = api_root / "analytics/military_score_inference/inference_table_stream_registry.py"
    forbidden = "api.streaming.table_stream.registry_catalog"
    assert not _module_imports_name(fleet_path, forbidden)
    assert not _module_imports_name(scores_path, forbidden)


class _AttachOnlyPolicy:
    """A connect policy for a stream with no players: it only attaches and detaches."""

    def __init__(self, scope: FleetTableStreamScope) -> None:
        self.scope = scope
        self.controller = object()
        self.streams_seen_at_attach: tuple[object, ...] = ()

    def attach(self) -> None:
        get_fleet_table_stream_registry().attach(self.scope, self.controller)
        self.streams_seen_at_attach = tuple(
            stream.controller for stream in live_table_streams(("fleet",))
        )

    def preamble_events(self) -> tuple[dict[str, object], ...]:
        return ()

    def detach(self) -> None:
        reset_fleet_table_stream_registry_for_tests()


@pytest.mark.usefixtures("empty_catalog")
def test_a_catalog_scan_catalogs_nothing_itself() -> None:
    get_fleet_table_stream_registry().attach(
        FleetTableStreamScope(game_id=10, perspective=2, turn_number=8), object()
    )

    assert active_table_stream_bindings() == ()
    assert live_table_streams(("fleet", "scores")) == ()


@pytest.mark.usefixtures("empty_catalog")
def test_stream_connect_catalogs_the_registries_before_the_controller_attaches(
    make_recording_table_stream_scheduler,
) -> None:
    scope = FleetTableStreamScope(game_id=10, perspective=2, turn_number=8)
    policy = _AttachOnlyPolicy(scope)

    events = list(
        iter_table_stream_connect_with_scope(
            scheduler=make_recording_table_stream_scheduler(),
            scope=scope,
            policy_factory=lambda _token: policy,
            player_ids=(),
        )
    )

    assert events == []
    assert policy.streams_seen_at_attach == (policy.controller,)


@pytest.mark.usefixtures("empty_catalog")
def test_cataloguing_twice_lists_each_registry_once() -> None:
    ensure_table_stream_registries_registered()
    ensure_table_stream_registries_registered()
    get_fleet_table_stream_registry().attach(
        FleetTableStreamScope(game_id=10, perspective=2, turn_number=8), object()
    )

    assert len(live_table_streams(("fleet",))) == 1


def test_active_table_stream_bindings_lists_fleet_and_scores_streams() -> None:
    fleet_scope = FleetTableStreamScope(game_id=10, perspective=2, turn_number=8)
    scores_scope = InferenceStreamScope(game_id=10, perspective=2, turn_number=8)
    get_fleet_table_stream_registry().attach(fleet_scope, object())
    get_inference_table_stream_registry().attach(scores_scope, object())

    bindings = active_table_stream_bindings()

    assert {
        "analyticId": "fleet",
        "gameId": 10,
        "perspective": 2,
        "turn": 8,
    } in bindings
    assert {
        "analyticId": "scores",
        "gameId": 10,
        "perspective": 2,
        "turn": 8,
    } in bindings


def test_live_table_streams_yield_attached_controllers_on_the_named_registries() -> None:
    fleet_scope = FleetTableStreamScope(game_id=10, perspective=2, turn_number=8)
    fleet_controller = object()
    get_fleet_table_stream_registry().attach(fleet_scope, fleet_controller)
    get_inference_table_stream_registry().attach(
        InferenceStreamScope(game_id=10, perspective=2, turn_number=8),
        object(),
    )

    (stream,) = live_table_streams(("fleet", "homeworld-locator"))

    assert (stream.analytic_id, stream.scope, stream.controller) == (
        "fleet",
        fleet_scope,
        fleet_controller,
    )


def test_a_captured_stream_is_live_only_while_its_own_controller_is_attached() -> None:
    scope = FleetTableStreamScope(game_id=10, perspective=2, turn_number=8)
    registry = get_fleet_table_stream_registry()
    first = SimpleNamespace(stream_token="first")
    registry.attach(scope, first)
    (captured_first,) = live_table_streams(("fleet",))
    assert captured_first.is_live()

    detach_fleet_table_stream("first")
    assert not captured_first.is_live()

    registry.attach(scope, first)
    (captured_reattached,) = live_table_streams(("fleet",))
    registry.attach(scope, SimpleNamespace(stream_token="second"))
    assert not captured_reattached.is_live()
    (captured_second,) = live_table_streams(("fleet",))
    assert captured_second.is_live()
