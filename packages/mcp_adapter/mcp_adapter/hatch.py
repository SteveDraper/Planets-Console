"""MCP export query hatch: list, hatch-read query, and background ensure."""

import json
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from api.analytics.catalog import TURN_ANALYTIC_CATALOG, catalog_entry
from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import (
    ExportProbeResult,
    ExportQueryResult,
    ExportScopeOverrides,
)
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.registry import EXPORT_REGISTRY
from api.compute.export_ensure import admit_export_scope_at_background
from api.serialization.codecs import dataclass_to_json
from api.services.game_service import GameService
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_load_service import TurnLoadService
from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Resolve
from mcp.types import CallToolResult, TextContent

from mcp_adapter.eligibility import require_eligible_perspective
from mcp_adapter.errors import CatalogTooBroadError, EmptyHatchPathsError
from mcp_adapter.shell_context import SHELL_CONTEXT_PROPERTIES

LIST_ANALYTIC_EXPORTS_TOOL = "list_analytic_exports"
QUERY_ANALYTIC_EXPORT_TOOL = "query_analytic_export"
ENSURE_ANALYTIC_EXPORT_TOOL = "ensure_analytic_export"

HATCH_TOOL_NAMES = (
    LIST_ANALYTIC_EXPORTS_TOOL,
    QUERY_ANALYTIC_EXPORT_TOOL,
    ENSURE_ANALYTIC_EXPORT_TOOL,
)

HATCH_TOOL_REQUIRED_PROPERTIES: dict[str, frozenset[str]] = {
    LIST_ANALYTIC_EXPORTS_TOOL: frozenset(),
    QUERY_ANALYTIC_EXPORT_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"analytic_id", "paths"}),
    ENSURE_ANALYTIC_EXPORT_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"analytic_id"}),
}

HATCH_TOOL_OPTIONAL_PROPERTIES: dict[str, frozenset[str]] = {
    LIST_ANALYTIC_EXPORTS_TOOL: frozenset({"analytic_id", "detail"}),
    QUERY_ANALYTIC_EXPORT_TOOL: frozenset({"player_id"}),
    ENSURE_ANALYTIC_EXPORT_TOOL: frozenset({"player_id", "dry_run"}),
}

HATCH_RESULT_BUDGET_BYTES = 65536
RESULT_TOO_LARGE_HINT = (
    "Narrow the query with a tighter JSONPath or a batched index list "
    "(for example $.solutions[0], $.solutions[1])."
)

CatalogDetailArg = Literal["summary", "full"]


def register_hatch_tools(
    mcp: MCPServer,
    *,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
    turn_analytic_service: TurnAnalyticService,
    export_registry: Mapping[str, AnalyticExportCatalog] | None = None,
) -> None:
    """Register the v1 MCP export query hatch tools."""
    registry = export_registry if export_registry is not None else EXPORT_REGISTRY
    _register_list_analytic_exports(mcp, resolve_login, registry)
    _register_query_analytic_export(
        mcp,
        game_service,
        turn_load_service,
        resolve_login,
        turn_analytic_service,
        registry,
    )
    _register_ensure_analytic_export(
        mcp,
        game_service,
        turn_load_service,
        resolve_login,
        turn_analytic_service,
        registry,
    )


def _register_list_analytic_exports(
    mcp: MCPServer,
    resolve_login: Callable[[Context], str],
    registry: Mapping[str, AnalyticExportCatalog],
) -> None:
    @mcp.tool(name=LIST_ANALYTIC_EXPORTS_TOOL)
    def list_analytic_exports(
        login: Annotated[str, Resolve(resolve_login)],
        analytic_id: str | None = None,
        detail: CatalogDetailArg | None = None,
    ) -> dict[str, Any]:
        """List analytic export catalogs for JSONPath hatch queries.

        Omit analytic_id for MCP export catalog summaries. Named analytic_id
        defaults to the full catalog (value schema, path-prefix rules, ordering,
        ensure dependencies). Omit-id plus detail=full is refused.
        """
        _ = login
        if analytic_id is None:
            resolved_detail = detail or "summary"
            if resolved_detail == "full":
                return _adapter_tool_error(
                    reason="catalog_too_broad",
                    text=str(CatalogTooBroadError()),
                )
            return {
                "exports": [
                    _summary_entry(aid, catalog) for aid, catalog in _iter_catalogs(registry)
                ]
            }

        catalog = registry.get(analytic_id)
        if catalog is None:
            return {"status": "unavailable", "reason": "unknown_analytic"}
        resolved_detail = detail or "full"
        if resolved_detail == "summary":
            return {"exports": [_summary_entry(analytic_id, catalog)]}
        return _full_entry(analytic_id, catalog)


def _register_query_analytic_export(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
    turn_analytic_service: TurnAnalyticService,
    registry: Mapping[str, AnalyticExportCatalog],
) -> None:
    @mcp.tool(name=QUERY_ANALYTIC_EXPORT_TOOL)
    def query_analytic_export(
        analytic_id: str,
        game_id: int,
        turn: int,
        perspective: int,
        paths: list[str],
        login: Annotated[str, Resolve(resolve_login)],
        player_id: int | None = None,
    ) -> dict[str, Any]:
        """Read an analytic export by JSONPath when the scope is already ensure-final.

        Does not start analytic export ensure. Materializes only persisted /
        ensure-final trees; otherwise unavailable with needs_ensure or in_progress.
        Poll after ensure_analytic_export until status is ok. Dialect is Core's
        subset: $, dotted names, [index], [*]. Empty paths is invalid.
        """
        if not paths:
            return _adapter_tool_error(
                reason="invalid_input",
                text=str(EmptyHatchPathsError()),
            )
        ctx = _hatch_query_context(
            game_service,
            turn_load_service,
            turn_analytic_service,
            registry,
            login_identity=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
            username="",
        )
        if ctx is None:
            return _json_ready(
                dataclass_to_json(ExportQueryResult(status="unavailable", reason="turn_not_stored"))
            )
        result = ctx.hatch_read(analytic_id, paths, _scope_overrides(player_id))
        payload = dataclass_to_json(result)
        if result.status != "ok":
            return _json_ready(payload)
        return _enforce_hatch_result_budget(payload)


def _register_ensure_analytic_export(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
    turn_analytic_service: TurnAnalyticService,
    registry: Mapping[str, AnalyticExportCatalog],
) -> None:
    @mcp.tool(name=ENSURE_ANALYTIC_EXPORT_TOOL)
    def ensure_analytic_export(
        analytic_id: str,
        game_id: int,
        turn: int,
        perspective: int,
        login: Annotated[str, Resolve(resolve_login)],
        player_id: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """dry_run first: probe missing ensure steps without starting compute.

        A live call admits analytic export ensure at background priority and
        returns immediately already_satisfied or accepted. It does not wait.
        Poll query_analytic_export until ok. No MCP Tasks.
        """
        ctx = _hatch_query_context(
            game_service,
            turn_load_service,
            turn_analytic_service,
            registry,
            login_identity=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
            username=login,
        )
        if ctx is None:
            return _json_ready(
                dataclass_to_json(ExportProbeResult(status="unavailable", reason="turn_not_stored"))
            )
        overrides = _scope_overrides(player_id)
        probe = ctx.probe(analytic_id, overrides)
        if dry_run:
            return _json_ready(dataclass_to_json(probe))
        if probe.status != "ok":
            return _json_ready(dataclass_to_json(probe))
        outcome = admit_export_scope_at_background(ctx, analytic_id, overrides)
        return {"status": outcome}


def _hatch_query_context(
    game_service: GameService,
    turn_load_service: TurnLoadService,
    turn_analytic_service: TurnAnalyticService,
    registry: Mapping[str, AnalyticExportCatalog],
    *,
    login_identity: str,
    game_id: int,
    turn: int,
    perspective: int,
    username: str,
) -> AnalyticQueryContext | None:
    require_eligible_perspective(
        game_service,
        login_identity=login_identity,
        game_id=game_id,
        perspective=perspective,
    )
    if not turn_load_service.is_turn_stored(game_id, perspective, turn):
        return None
    return turn_analytic_service.export_query_context(
        game_id,
        perspective,
        turn,
        username=username,
        export_registry=registry,
    )


def _scope_overrides(player_id: int | None) -> ExportScopeOverrides:
    return ExportScopeOverrides(player_id=player_id)


def _iter_catalogs(
    registry: Mapping[str, AnalyticExportCatalog],
) -> list[tuple[str, AnalyticExportCatalog]]:
    catalog_ids = [entry.id for entry in TURN_ANALYTIC_CATALOG if entry.id in registry]
    extras = [analytic_id for analytic_id in registry if analytic_id not in catalog_ids]
    return [(analytic_id, registry[analytic_id]) for analytic_id in catalog_ids + extras]


def _catalog_name(analytic_id: str) -> str:
    try:
        return catalog_entry(analytic_id).name
    except KeyError:
        return analytic_id


def _catalog_description(catalog: AnalyticExportCatalog) -> str:
    if catalog.is_empty:
        return "empty-catalog"
    schema = catalog.value_schema
    if isinstance(schema, dict):
        description = schema.get("description")
        if isinstance(description, str) and description:
            return description
    return ""


def _summary_entry(analytic_id: str, catalog: AnalyticExportCatalog) -> dict[str, Any]:
    return {
        "analytic_id": analytic_id,
        "name": _catalog_name(analytic_id),
        "description": _catalog_description(catalog),
        "is_empty": catalog.is_empty,
    }


def _full_entry(analytic_id: str, catalog: AnalyticExportCatalog) -> dict[str, Any]:
    return {
        **_summary_entry(analytic_id, catalog),
        "value_schema": catalog.value_schema,
        "path_prefix_scope_rules": [
            {"prefix": rule.prefix, "requires": list(rule.requires)}
            for rule in catalog.path_prefix_scope_rules
        ],
        "ordering_semantics": dict(catalog.ordering_semantics),
        "ensure_dependencies": [
            dataclass_to_json(dependency) for dependency in catalog.ensure_dependencies
        ],
    }


def _hatch_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _json_object(serialized: str) -> dict[str, Any]:
    loaded = json.loads(serialized)
    if not isinstance(loaded, dict):
        raise TypeError("hatch payload must serialize to a JSON object")
    return loaded


def _json_ready(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-native dict (tuples become lists; matches MCP structured content)."""
    return _json_object(_hatch_json_text(payload))


def _enforce_hatch_result_budget(payload: dict[str, Any]) -> dict[str, Any] | CallToolResult:
    serialized = _hatch_json_text(payload)
    byte_count = len(serialized.encode("utf-8"))
    if byte_count <= HATCH_RESULT_BUDGET_BYTES:
        return _json_object(serialized)
    return _adapter_tool_error(
        reason="result_too_large",
        text=(
            f"Hatch query result is {byte_count} bytes; "
            f"budget is {HATCH_RESULT_BUDGET_BYTES}. {RESULT_TOO_LARGE_HINT}"
        ),
        bytes=byte_count,
        budget_bytes=HATCH_RESULT_BUDGET_BYTES,
        hint=RESULT_TOO_LARGE_HINT,
        paths={},
    )


def _adapter_tool_error(*, reason: str, text: str, **fields: Any) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        is_error=True,
        structured_content={"reason": reason, **fields},
    )
