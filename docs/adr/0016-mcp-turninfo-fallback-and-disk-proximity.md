# MCP TurnInfo is a fallback; v1 requires disk proximity

Status: accepted

An MCP advisor that treats stored **TurnInfo** as the primary interface will spend tokens scanning JSON for questions that are cheap and exact in code -- especially geometry ("what is near what"). Human-parity for the first MCP slice is **information** parity with Console analysis, not a turn dump and not BFF table/map JSON ([ADR 0015](0015-mcp-adapter-package.md)).

**TurnInfo** remains available under the **MCP visibility ceiling** ([ADR 0014](0014-mcp-login-identity-and-visibility.md)), but only as **MCP TurnInfo fallback**: a last-resort read of a *named* object's fields when no distilled query covers them. Scan, filter, geometry, or other compute over a collection is a capability hole, not a reason to dump the turn. MCP tool descriptions must steer agents to distilled queries.

The first slice is incomplete without **MCP disk proximity**: ships, planets, and cartography features within a light-year radius of a map coordinate. Core has no such product query today (`iter_planets_within_radius` is planets-only and internal; `sample_at` is a point). Filling that gap is a Core concept, not MCP-layer logic, and means wrap-only existing helpers cannot finish v1 ([Whether v1 MCP wraps only existing Core concepts or adds new query helpers](https://github.com/SteveDraper/Planets-Console/issues/321)).

## Considered options

- **TurnInfo dump as the advisor API** -- rejected; LLM distance, filtering, and "what is close to what" over turn JSON is inefficient and error-prone compared to in-process queries.
- **No TurnInfo on MCP** -- rejected; named-object field reads (ship 42's friendly code, planet 17's natives) are a legitimate fallback when no distilled path exists.
- **Policy only, ship v1 without disk proximity** -- rejected; that ships the failure mode the fallback rule exists to prevent.
- **Close every advisor-family hole in v1** (fuel, mines, combat, host-order, collection search) -- rejected; that is the destination, not the first slice. Those remain holes under the fallback rule but are not v1 gates.
- **Human-parity as BFF table/map JSON** -- already rejected in [ADR 0015](0015-mcp-adapter-package.md).

## Consequences

- First-slice contents (read-only analysis parity, existing concept HTTP, **turn-ensure** / **GameInfo** refresh, diagnostics never, mutations and **load-all** later) live in [design-mcp.md](../design-mcp.md), not this ADR.
- Catalog shape is [ADR 0017](0017-mcp-catalog-named-tools-and-export-hatch.md) (named gameplay tools plus **MCP export query hatch**; tools only). Stream and trigger-vs-persisted compute remain [How analytic exports and live analytics appear on MCP](https://github.com/SteveDraper/Planets-Console/issues/319).
- Glossary: **MCP TurnInfo fallback**, **MCP disk proximity** in [CONTEXT.md](../../CONTEXT.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [What human-parity means for the first MCP slice](https://github.com/SteveDraper/Planets-Console/issues/316).
