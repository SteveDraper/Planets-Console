# MCP export hatch is describe, read-only query, and explicit ensure

Status: accepted

The **MCP export query hatch** needed exact tool names, whether query triggers **analytic export ensure**, and whether SPA live delivery (table/map GET, **table stream**s) appears on MCP ([How analytic exports and live analytics appear on MCP](https://github.com/SteveDraper/Planets-Console/issues/319)). Catalog philosophy is already hybrid ([ADR 0017](0017-mcp-catalog-named-tools-and-export-hatch.md)).

v1 analytic *results* on MCP are this hatch plus **MCP named gameplay tool**s -- not BFF table/map twins and not MCP table streams. Three tools: `list_analytic_exports` (optional `analytic_id`; `detail=summary|full`), `query_analytic_export` (same envelope as in-process; does not admit new ensure; materializes only persisted / ensure-final), `ensure_analytic_export` (`dry_run` = **analytic export ensure probe**; live call returns immediately `already_satisfied` or `accepted`). Query `unavailable` reasons include `needs_ensure` and `in_progress`. The agent polls query until `ok`. No MCP Tasks in v1. Live ensure admits via Core **analytic export ensure** in-process (same path as Core; orchestrator DAG via [#204](https://github.com/SteveDraper/Planets-Console/issues/204)). MCP does not expose `ComputeRequest` and does not wait on [Compute orchestrator (phase 3): uniform BFF compute API](https://github.com/SteveDraper/Planets-Console/issues/203). See [How this MCP product relates to orchestrator phase 3](https://github.com/SteveDraper/Planets-Console/issues/320) and [ADR 0005](0005-compute-orchestrator.md).

## Considered options

- **Table/map GET or table streams as MCP tools** -- rejected; human-parity is information, not BFF JSON ([ADR 0015](0015-mcp-adapter-package.md), [ADR 0016](0016-mcp-turninfo-fallback-and-disk-proximity.md)). Streams are SPA progressive-render.
- **Query always ensures** (in-process `ctx.query` parity) -- rejected; a curious JSONPath can unwind decades of fleet/scores with no SPA confirm UX and can hang `tools/call`.
- **Query with an `ensure` flag** -- rejected; too easy to pass `true` while exploring.
- **Cheap inline ensure on query, large work via ensure tool** -- rejected; side effects on query depend on a threshold the agent cannot see.
- **MCP Tasks for long ensure** -- rejected for v1; polling query is the durable handle ([MCP 2026-07-28 protocol and Python SDK for an in-process host](https://github.com/SteveDraper/Planets-Console/issues/311)).
- **Materialize in-progress / partial trees on query** -- deferred; v1 `ok` means ensure-final. A later option may surface partial state with an explicit non-final indicator.
- **Required `analytic_id` on list only** -- rejected; omit-id summary lets the agent browse without guessing ids or pulling every schema.
- **`describe_analytic_exports` instead of `list_analytic_exports`** -- rejected; keep the [#98](https://github.com/SteveDraper/Planets-Console/issues/98) names and add `ensure_analytic_export` in the same vocabulary.

## Consequences

- `UnavailableReason` gains `needs_ensure` and `in_progress` (Core-visible, one vocabulary -- not an MCP-only enum).
- `list_analytic_exports` omit-id defaults to **MCP export catalog summary**; named id defaults to full catalog. Explicit `detail` overrides. Omit-id + full is allowed and large.
- Query and ensure are turn-scoped (**shell context**); list is login-only ([ADR 0018](0018-mcp-shell-context-binding.md)).
- Glossary: **MCP export query hatch**, **MCP export catalog summary** in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md). Export Future MCP: [design-analytic-exports.md](../design-analytic-exports.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [How analytic exports and live analytics appear on MCP](https://github.com/SteveDraper/Planets-Console/issues/319).
