"""In-process MCP export hatch: hatch-read equality and adapter-only errors."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import (
    ExportProbeResult,
    ExportQueryResult,
    ExportScopeOverrides,
    PathPrefixScopeRule,
    PathResult,
)
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.registry import merge_export_registry
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import GameInfo
from api.serialization.codecs import dataclass_to_json
from mcp_adapter.hatch import (
    ENSURE_ANALYTIC_EXPORT_TOOL,
    HATCH_RESULT_BUDGET_BYTES,
    LIST_ANALYTIC_EXPORTS_TOOL,
    QUERY_ANALYTIC_EXPORT_TOOL,
    RESULT_TOO_LARGE_HINT,
)

from tests.mcp_test_support import build_test_mcp, call_tool, resolve_as, stored_turn_mcp

_FIXTURE_PATHS = ["$.payload.label"]
_OWN_SLOT = 2
_FIXTURE_PLAYER_ID = 8


def _json_ready(obj: object) -> dict:
    payload = obj if isinstance(obj, dict) else dataclass_to_json(obj)
    return json.loads(json.dumps(payload))


def _shell(turn, *, perspective: int = _OWN_SLOT) -> dict:
    return {
        "game_id": turn.game.id,
        "turn": turn.settings.turn,
        "perspective": perspective,
    }


def _fixture_export_registry() -> dict[str, AnalyticExportCatalog]:
    catalog = AnalyticExportCatalog(
        analytic_id="export-test-alpha",
        value_schema={
            "type": "object",
            "description": "Fixture hatch tree for MCP adapter equality tests.",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": "Fixture payload branch.",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Scope-identifying label.",
                        },
                    },
                },
            },
        },
        path_prefix_scope_rules=(PathPrefixScopeRule(prefix="$.payload", requires=("player_id",)),),
        materialize_export_tree=lambda _ctx, scope: {
            "payload": {"label": f"alpha-t{scope.turn}-p{scope.player_id}"}
        },
        is_persisted=lambda _ctx, _scope: True,
    )
    return merge_export_registry(catalog)


def test_list_omit_id_returns_summaries_not_full_schema():
    mcp = build_test_mcp()

    result = call_tool(mcp, LIST_ANALYTIC_EXPORTS_TOOL, {})

    assert result.is_error is False
    payload = result.structured_content
    assert "exports" in payload
    ids = [entry["analytic_id"] for entry in payload["exports"]]
    assert "connections" in ids
    assert "scores" in ids
    for entry in payload["exports"]:
        assert set(entry) == {"analytic_id", "name", "description", "is_empty"}
        assert "value_schema" not in entry
    connections = next(
        entry for entry in payload["exports"] if entry["analytic_id"] == "connections"
    )
    assert connections["is_empty"] is True
    assert connections["description"] == "empty-catalog"


def test_list_omit_id_full_is_catalog_too_broad():
    mcp = build_test_mcp()

    result = call_tool(mcp, LIST_ANALYTIC_EXPORTS_TOOL, {"detail": "full"})

    assert result.is_error is True
    assert result.structured_content["reason"] == "catalog_too_broad"
    assert "analytic_id" in result.content[0].text


def test_list_named_full_includes_catalog_schema_not_value_tree():
    mcp = build_test_mcp()

    result = call_tool(mcp, LIST_ANALYTIC_EXPORTS_TOOL, {"analytic_id": "scores"})

    assert result.is_error is False
    payload = result.structured_content
    assert payload["analytic_id"] == "scores"
    assert payload["is_empty"] is False
    assert "value_schema" in payload
    assert "path_prefix_scope_rules" in payload
    assert "ordering_semantics" in payload
    assert "ensure_dependencies" in payload
    assert "solutions" not in payload


def test_query_connections_matches_hatch_read(running_game_info: GameInfo, sample_turn):
    mcp, _, _ = stored_turn_mcp(running_game_info, sample_turn)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        game_id=sample_turn.game.id,
        perspective=_OWN_SLOT,
    )
    hatch = ctx.hatch_read("connections", ["$"])

    result = call_tool(
        mcp,
        QUERY_ANALYTIC_EXPORT_TOOL,
        {**_shell(sample_turn), "analytic_id": "connections", "paths": ["$"]},
    )

    assert result.is_error is False
    assert result.structured_content == _json_ready(hatch)
    assert hatch.reason == "empty_catalog"


def test_query_fixture_catalog_matches_hatch_read(running_game_info: GameInfo, sample_turn):
    registry = _fixture_export_registry()
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        game_id=sample_turn.game.id,
        perspective=_OWN_SLOT,
        export_registry=registry,
    )
    hatch = ctx.hatch_read(
        "export-test-alpha",
        _FIXTURE_PATHS,
        ExportScopeOverrides(player_id=_FIXTURE_PLAYER_ID),
    )
    mcp, games, turns = stored_turn_mcp(running_game_info, sample_turn)
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        export_registry=registry,
        resolve_login=resolve_as("arlowat"),
    )

    result = call_tool(
        mcp,
        QUERY_ANALYTIC_EXPORT_TOOL,
        {
            **_shell(sample_turn),
            "analytic_id": "export-test-alpha",
            "paths": _FIXTURE_PATHS,
            "player_id": _FIXTURE_PLAYER_ID,
        },
    )

    assert hatch.status == "ok"
    assert hatch.paths[_FIXTURE_PATHS[0]].value == (
        f"alpha-t{sample_turn.settings.turn}-p{_FIXTURE_PLAYER_ID}"
    )
    assert result.is_error is False
    assert result.structured_content == _json_ready(hatch)


def test_query_empty_paths_is_invalid_input(running_game_info: GameInfo, sample_turn):
    mcp, _, _ = stored_turn_mcp(running_game_info, sample_turn)

    result = call_tool(
        mcp,
        QUERY_ANALYTIC_EXPORT_TOOL,
        {**_shell(sample_turn), "analytic_id": "connections", "paths": []},
    )

    assert result.is_error is True
    assert result.structured_content["reason"] == "invalid_input"


def test_query_over_budget_is_result_too_large_with_zero_path_values(
    running_game_info: GameInfo,
    sample_turn,
    monkeypatch,
):
    mcp, _, _ = stored_turn_mcp(running_game_info, sample_turn)
    huge = ExportQueryResult(
        status="ok",
        paths={"$": PathResult(kind="value", value="x" * 200)},
    )
    monkeypatch.setattr("mcp_adapter.hatch.HATCH_RESULT_BUDGET_BYTES", 32)

    with patch(
        "mcp_adapter.hatch.AnalyticQueryContext.hatch_read",
        return_value=huge,
    ):
        result = call_tool(
            mcp,
            QUERY_ANALYTIC_EXPORT_TOOL,
            {**_shell(sample_turn), "analytic_id": "scores", "paths": ["$"]},
        )

    assert result.is_error is True
    payload = result.structured_content
    assert payload["reason"] == "result_too_large"
    assert payload["budget_bytes"] == 32
    assert payload["bytes"] > 32
    assert payload["paths"] == {}
    assert payload["hint"] == RESULT_TOO_LARGE_HINT
    assert HATCH_RESULT_BUDGET_BYTES == 65536


def test_query_refuses_ineligible_perspective(running_game_info: GameInfo, sample_turn):
    from api.services.game_service import GameService
    from api.services.turn_load_service import TurnLoadService

    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = True
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
    )

    result = call_tool(
        mcp,
        QUERY_ANALYTIC_EXPORT_TOOL,
        {
            "game_id": sample_turn.game.id,
            "turn": sample_turn.settings.turn,
            "perspective": 1,
            "analytic_id": "connections",
            "paths": ["$"],
        },
    )

    assert result.is_error is True
    assert "Perspective 1 is not allowed" in result.content[0].text
    turns.get_turn_info.assert_not_called()


def test_ensure_dry_run_matches_probe(running_game_info: GameInfo, sample_turn):
    mcp, _, _ = stored_turn_mcp(running_game_info, sample_turn)
    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        game_id=sample_turn.game.id,
        perspective=_OWN_SLOT,
    )
    probe = ctx.probe("connections")

    result = call_tool(
        mcp,
        ENSURE_ANALYTIC_EXPORT_TOOL,
        {**_shell(sample_turn), "analytic_id": "connections", "dry_run": True},
    )

    assert result.is_error is False
    assert result.structured_content == _json_ready(probe)


def test_ensure_live_returns_immediately_without_waiting(
    running_game_info: GameInfo,
    sample_turn,
):
    mcp, _, _ = stored_turn_mcp(running_game_info, sample_turn)
    handle = MagicMock()
    handle.wait.side_effect = AssertionError("MCP hatch ensure must not wait")

    with (
        patch(
            "mcp_adapter.hatch.AnalyticQueryContext.probe",
            return_value=ExportProbeResult(status="ok"),
        ),
        patch(
            "mcp_adapter.hatch.admit_export_scope_at_background",
            return_value="accepted",
        ) as admit,
    ):
        result = call_tool(
            mcp,
            ENSURE_ANALYTIC_EXPORT_TOOL,
            {**_shell(sample_turn), "analytic_id": "scores", "player_id": 8},
        )

    assert result.is_error is False
    assert result.structured_content == {"status": "accepted"}
    admit.assert_called_once()
    handle.wait.assert_not_called()
