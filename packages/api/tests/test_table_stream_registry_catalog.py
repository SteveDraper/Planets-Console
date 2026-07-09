"""Tests for analytic-agnostic table-stream registry catalog registration."""

from __future__ import annotations

import ast
from pathlib import Path

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
from api.streaming.table_stream.registry_catalog import (
    active_table_stream_bindings,
    reset_table_stream_registry_catalog_for_tests,
)


def setup_function() -> None:
    reset_table_stream_registry_catalog_for_tests()
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()


def teardown_function() -> None:
    reset_table_stream_registry_catalog_for_tests()
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()


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
    scores_path = (
        api_root / "analytics/military_score_inference/inference_table_stream_registry.py"
    )
    forbidden = "api.streaming.table_stream.registry_catalog"
    assert not _module_imports_name(fleet_path, forbidden)
    assert not _module_imports_name(scores_path, forbidden)


def test_active_table_stream_bindings_registers_from_central_bootstrap() -> None:
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
