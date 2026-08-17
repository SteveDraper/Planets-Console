# MCP v1 contract is tool registration; tests split adapter, Core hatch-read, and server smoke

Status: accepted

v1 MCP needs a contract artifact and a test split so the adapter does not grow a second OpenAPI, a BFF-style HTTP matrix, or literal equality with `ctx.query` ([MCP testing and contract strategy](https://github.com/SteveDraper/Planets-Console/issues/328)). Original [#98](https://github.com/SteveDraper/Planets-Console/issues/98) asked MCP hatch results to match in-process for the same scope/paths; [ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md) then made hatch query ensure-final only, so that sentence is now the **hatch-read** path, not `ctx.query`.

The live contract is MCP `server/discover` plus `tools/list` **input schemas** from SDK registration in `mcp_adapter` -- the same table that registers tools. Tests lock the exact v1 name set (5 **MCP shell tool**s + 15 **MCP named gameplay tool**s + 3 hatch tools) and required input properties. No OpenAPI for `/mcp` (that pipeline is **BFF contract codegen** for the SPA). No checked-in golden of free-text `description`s; assert only ADR-mandated phrases (`hyperjump_landing` pre-well-snap nudge; ensure `dry_run` first). Hatch **value** trees stay Core **analytic export catalog** goldens.

Tests split by owner. `packages/api` owns the hatch-read contract (`needs_ensure` / `in_progress` / ensure-final envelope), fixture alpha/beta gates, and that `ctx.query` still admits ensure -- plus concept math, including **MCP disk proximity**. `packages/mcp_adapter` owns in-process handler tests: wrap mapping (not concept math), catalog name/inputSchema lock, thin equality of `query_analytic_export` to the Core hatch-read function (one fixture case plus **connections**), and adapter-only errors (`result_too_large`, `catalog_too_broad`, missing **MCP login identity**, missing **shell context**, **viewpoint eligibility** refuse). `packages/server` owns a thin Streamable HTTP smoke: `POST /mcp` `server/discover` is tools-only, root `session_manager` lifespan, Origin 403, login fail-closed -- not one HTTP test per tool.

`make test` / `ci` / `ci_full` gain `test_mcp_adapter`. `lint` includes `packages/mcp_adapter`. HTTP smoke stays on existing `test_server`.

## Considered options

- **OpenAPI or a dumped JSON Schema file as a second artifact** -- rejected; parallel ladder with SPA codegen; agents consume `tools/list`.
- **Checked-in golden of full `tools/list` including descriptions** -- rejected; agent-facing prose will churn.
- **HTTP-first matrix** (every tool through Streamable HTTP `TestClient`) -- rejected; copies the BFF suite onto MCP and still would not prove hatch == Core.
- **Adapter unit only** -- rejected; mount + root lifespan is the easy-to-miss composition bug.
- **Literal #98 equality with `ctx.query`** -- rejected; contradicts [ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md).
- **All hatch tests in `mcp_adapter`** -- rejected; hatch-read is Core vocabulary ([ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md)); the adapter owns no domain logic ([ADR 0015](0015-mcp-adapter-package.md)).
- **Re-golden export trees in `mcp_adapter`** -- rejected; Core already goldens **connections** / **scores**.
- **Scores/fleet ensure in the adapter suite** -- rejected; expensive, already Core.

## Consequences

- Hatch oversize remains adapter transport ([ADR 0024](0024-mcp-result-size-and-query-cost.md)); parity tests use in-budget paths.
- Design index: [design-mcp.md](../design-mcp.md). Export Future MCP: [design-analytic-exports.md](../design-analytic-exports.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [MCP testing and contract strategy](https://github.com/SteveDraper/Planets-Console/issues/328).
