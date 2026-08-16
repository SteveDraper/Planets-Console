# MCP hatch payloads are budgeted in the adapter; ensure admits at background

Status: accepted

v1 MCP needs limits so tool results fit an agent context window and hatch **analytic export ensure** does not jump SPA work ([MCP pagination, result size, and query-cost controls](https://github.com/SteveDraper/Planets-Console/issues/327)). MCP 2026-07-28 pagination applies only to list operations (`tools/list`, `resources/list`, `prompts/list`, `resources/templates/list`), not `tools/call`. v1 does not declare that utility.

Payload policy is split. **MCP shell tool**s, **MCP named gameplay tool**s, and **MCP TurnInfo fallback** are already bounded by the catalog (one entity, disk-proximity hit stubs, GameInfo, turn-ensure status) -- no extra cap, no in-band pagination, no truncation. `ensure_turn` stays the existing synchronous loadturn wait; this ADR adds no second timeout. The **MCP export query hatch** is where size and cost live.

`query_analytic_export` takes a non-empty `paths` list -- the same **batched export query** as in-process Core, not a single JSONPath string. The dialect stays Core's RFC 9535-ish subset (`$`, dotted names, `[index]`, `[*]`). No slice (`[:3]`) and no filter selectors; top-K is `["$.solutions[0]", "$.solutions[1]", "$.solutions[2]"]`. After Core returns `ok`, **mcp_adapter** serializes the successful envelope and enforces the **MCP hatch result budget** (v1: 65536 UTF-8 bytes, named constant, not a tool argument). Over budget is an MCP tool error (`isError`, `reason: "result_too_large"`, `bytes`, `budget_bytes`, narrowing hint) with zero path values -- not Core `unavailable`, not a truncated tree. Core `ctx.query` between analytics is uncapped.

`list_analytic_exports` omit-id stays **MCP export catalog summary**. Omit-id + `detail=full` is refused (`catalog_too_broad`); named `analytic_id` + full catalog remains the schema path. That revises [ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md) (omit-id + full is no longer allowed).

Live `ensure_analytic_export` still returns immediately `already_satisfied` or `accepted` ([ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md)). Admit uses the same Core **analytic export ensure** path but must not wait (`ensure_export_scope_via_orchestrator` is the waiter helper; MCP is not that caller). Submits at `background`, not `interactive_ensure` or `stream_attached`. No MCP-specific timeout, no cheap-vs-expensive threshold, no concurrent-root cap, no MCP Tasks. Tool descriptions require `dry_run` first; the protocol does not enforce the two-step. Localhost single-user ([ADR 0023](0023-mcp-v1-client-connection.md)); orchestrator singleflight still coalesces duplicate scopes.

## Considered options

- **MCP protocol pagination for tool results** -- rejected; the spec does not page `tools/call`. Catalog size does not need `tools/list` paging.
- **Uniform byte cap on every tool** -- rejected; named/shell/fallback payloads are already small; a uniform cap either false-fires or fails to stop hatch `$`.
- **Truncation-with-indicator** -- rejected; a silently shortened `$.solutions` array is a lying advisor.
- **In-band cursor/limit on hatch query** -- rejected; JSONPath is a tree. Narrowing is a tighter path or a batched index list.
- **Core `UnavailableReason` for oversize** -- rejected; the tree was established. Over-budget is adapter transport, not domain unavailability. Putting the cap in Core would tax in-process `ctx.query`.
- **Expand Core JSONPath with slices or filters** -- rejected for this map; top-K is already batched indices. Threshold-on-`objectiveValue` stays a later hole.
- **Wait on hatch ensure / MCP Tasks / cheap-vs-expensive threshold** -- already rejected in [ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md).
- **Hatch ensure at `interactive_ensure`** -- rejected; that is Core's waiter default and would let an MCP curiosity jump SPA streams (`stream_attached`) and interactive ensure.
- **Protocol-enforced dry_run-then-ensure** -- rejected; busywork the agent will skip. Description plus `dry_run` is enough.
- **Concurrent MCP-ensure root cap** -- rejected for v1; localhost single-user.

## Consequences

- Glossary: **MCP hatch result budget** in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md). Export Future MCP: [design-analytic-exports.md](../design-analytic-exports.md).
- `list_analytic_exports` omit-id + full is a shape refuse, not the byte budget.

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [MCP pagination, result size, and query-cost controls](https://github.com/SteveDraper/Planets-Console/issues/327).
