"""Tests for analytic export framework fixture analytics."""

import json
from pathlib import Path

import pytest
from api.analytics.export_errors import ExportCycleDetectedError
from api.analytics.export_types import ExportScopeOverrides
from api.analytics.exports.jsonpath import parse_jsonpath, resolve_jsonpath
from api.analytics.exports.registry import EXPORT_REGISTRY
from api.serialization.turn import turn_info_from_json

from tests.fixtures.export_framework.harness import (
    build_stored_turn_chain,
    first_player_id,
    make_cycle_fixture_query_context,
    make_fixture_query_context,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        return turn_info_from_json(json.load(handle))


def test_export_registry_covers_production_catalog():
    from api.analytics.catalog import TURN_ANALYTIC_CATALOG
    from api.analytics.registry import TURN_ANALYTIC_REGISTRATIONS

    catalog_ids = {entry.id for entry in TURN_ANALYTIC_CATALOG}
    assert set(EXPORT_REGISTRY) == catalog_ids
    for registration in TURN_ANALYTIC_REGISTRATIONS:
        analytic_id = registration.catalog_entry.id
        assert EXPORT_REGISTRY[analytic_id].analytic_id == analytic_id
        assert registration.export_catalog is EXPORT_REGISTRY[analytic_id]


def test_jsonpath_resolver_supports_index_and_wildcard():
    document = {
        "payload": {
            "items": [{"id": 1}, {"id": 2}],
            "label": "ok",
        }
    }
    assert resolve_jsonpath(document, "$.payload.label") == ["ok"]
    assert resolve_jsonpath(document, "$.payload.items[0].id") == [1]
    assert resolve_jsonpath(document, "$.payload.items[*].id") == [1, 2]
    assert resolve_jsonpath(document, "$.payload.items[9]") == []
    with pytest.raises(ValueError):
        parse_jsonpath("not-a-path")


def test_probe_reports_missing_steps_before_ensure(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=3)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    probe = ctx.probe(
        "export-test-alpha",
        ExportScopeOverrides(turn=3, player_id=player_id),
    )

    assert probe.total_missing >= 2
    assert probe.status == "ok"
    assert not probe.blocked_inline
    assert any(
        step.analytic_id == "export-test-alpha" and step.turn == 3 for step in probe.missing_steps
    )
    assert any(
        step.analytic_id == "export-test-beta" and step.turn == 2 for step in probe.missing_steps
    )


def test_inline_ensure_materializes_fixture_export(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    result = ctx.query(
        "export-test-alpha",
        ["$.payload.label"],
        ExportScopeOverrides(turn=2, player_id=player_id),
    )

    assert result.status == "ok"
    assert result.paths["$.payload.label"].kind == "value"
    assert result.paths["$.payload.label"].value == f"alpha-t2-p{player_id}"
    assert len(ctx._ensured_scopes) >= 1


def test_cross_turn_chain_is_allowed_without_cycle_error(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=3)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    result = ctx.query(
        "export-test-alpha",
        ["$.payload.label"],
        ExportScopeOverrides(turn=3, player_id=player_id),
    )

    assert result.status == "ok"
    assert result.paths["$.payload.label"].value == f"alpha-t3-p{player_id}"


def test_turn_not_stored_returns_unavailable(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = {sample_turn.settings.turn: sample_turn}
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    result = ctx.query(
        "export-test-alpha",
        ["$.payload.label"],
        ExportScopeOverrides(turn=sample_turn.settings.turn - 1, player_id=player_id),
    )

    assert result.status == "unavailable"
    assert result.reason == "turn_not_stored"


def test_none_vs_unavailable_for_missing_index(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    result = ctx.query(
        "export-test-alpha",
        ["$.payload.items[0]"],
        ExportScopeOverrides(turn=2, player_id=player_id),
    )

    assert result.status == "ok"
    assert result.paths["$.payload.items[0]"].kind == "none"


def test_invalid_scope_without_player_id(sample_turn):
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    result = ctx.query(
        "export-test-alpha",
        ["$.payload.label"],
        ExportScopeOverrides(turn=2),
    )

    assert result.status == "unavailable"
    assert result.reason == "invalid_scope"


def test_query_memoizes_identical_resolution(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)
    scope = ExportScopeOverrides(turn=2, player_id=player_id)

    first = ctx.query("export-test-alpha", ["$.payload.label"], scope)
    materialize_calls_after_first = len(ctx._materialized_trees)
    second = ctx.query("export-test-alpha", ["$.payload.label"], scope)

    assert first == second
    assert materialize_calls_after_first == len(ctx._materialized_trees)


def test_cycle_detection_raises(sample_turn):
    from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE

    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)
    FIXTURE_EXPORT_STATE.cycle_on_materialize = True

    with pytest.raises(ExportCycleDetectedError):
        ctx.query(
            "export-test-alpha",
            ["$.payload.label"],
            ExportScopeOverrides(turn=2, player_id=player_id),
        )


def test_ensure_graph_cycle_raises(sample_turn):
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_cycle_fixture_query_context(sample_turn, stored_turns=stored_turns)

    with pytest.raises(ExportCycleDetectedError, match="ensure cycle"):
        ctx.query(
            "export-test-cycle-a",
            ["$.payload.label"],
            ExportScopeOverrides(turn=2, player_id=player_id),
        )


def test_large_probe_blocks_inline_ensure(sample_turn, monkeypatch):
    from api.analytics import export_context as export_context_module

    monkeypatch.setattr(export_context_module, "INLINE_ENSURE_MAX_MISSING_STEPS", 0)
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    probe = ctx.probe(
        "export-test-alpha",
        ExportScopeOverrides(turn=2, player_id=player_id),
    )
    assert probe.status == "ok"
    assert probe.blocked_inline

    result = ctx.query(
        "export-test-alpha",
        ["$.payload.label"],
        ExportScopeOverrides(turn=2, player_id=player_id),
    )
    assert result.status == "unavailable"
    assert result.reason == "ensure_blocked"


def test_force_inline_ensure_bypasses_blocked_threshold(sample_turn, monkeypatch):
    from api.analytics import export_context as export_context_module

    monkeypatch.setattr(export_context_module, "INLINE_ENSURE_MAX_MISSING_STEPS", 0)
    player_id = first_player_id(sample_turn)
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    ctx = make_fixture_query_context(sample_turn, stored_turns=stored_turns)

    probe = ctx.probe(
        "export-test-alpha",
        ExportScopeOverrides(turn=2, player_id=player_id),
    )
    assert probe.status == "ok"
    assert probe.blocked_inline

    result = ctx.query(
        "export-test-alpha",
        ["$.payload.label"],
        ExportScopeOverrides(turn=2, player_id=player_id),
        force_inline_ensure=True,
    )

    assert result.status == "ok"
    assert result.paths["$.payload.label"].kind == "value"
    assert result.paths["$.payload.label"].value == f"alpha-t2-p{player_id}"


def test_probe_unknown_analytic_returns_unavailable(sample_turn):
    ctx = make_fixture_query_context(sample_turn)

    probe = ctx.probe("missing-analytic")

    assert probe.status == "unavailable"
    assert probe.reason == "unknown_analytic"
    assert probe.total_missing == 0
    assert probe.missing_steps == ()


def test_probe_empty_catalog_returns_unavailable(sample_turn):
    from api.analytics import TurnAnalyticsOptions
    from api.analytics.compute_context import make_analytic_compute_context

    ctx = make_analytic_compute_context(sample_turn, TurnAnalyticsOptions())

    probe = ctx.exports.probe("base-map")

    assert probe.status == "unavailable"
    assert probe.reason == "empty_catalog"
    assert probe.total_missing == 0
    assert probe.missing_steps == ()


def test_get_turn_analytic_wires_query_context(sample_turn):
    from api.analytics import TurnAnalyticsOptions, get_turn_analytic

    data = get_turn_analytic("base-map", sample_turn, TurnAnalyticsOptions())
    assert data["analyticId"] == "base-map"

    from api.analytics.compute_context import make_analytic_compute_context

    ctx = make_analytic_compute_context(sample_turn, TurnAnalyticsOptions())
    empty_probe = ctx.exports.probe("base-map")
    assert empty_probe.status == "unavailable"
    assert empty_probe.reason == "empty_catalog"
    empty_result = ctx.exports.query("base-map", ["$.meta"])
    assert empty_result.status == "unavailable"
    assert empty_result.reason == "empty_catalog"
