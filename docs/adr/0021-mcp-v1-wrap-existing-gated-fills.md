# v1 MCP wraps existing Core concepts; only gated new helpers

Status: accepted

v1 **MCP named gameplay tool**s wrap query math that already lives in Core `api/concepts/`, whether or not that math has concept HTTP. A new Core helper is added only when a first-slice gate requires it. The only such gate is **MCP disk proximity** ([ADR 0016](0016-mcp-turninfo-fallback-and-disk-proximity.md)). Filling a gap is always a Core **game concept**, never MCP-adapter math. This map does not add concept HTTP; MCP calls Core in-process ([ADR 0015](0015-mcp-adapter-package.md)).

## Considered options

- **Strict wrap-only** (no new Core helpers at all) -- rejected; wrap-only cannot close **MCP disk proximity**, which [ADR 0016](0016-mcp-turninfo-fallback-and-disk-proximity.md) treats as a v1 gate.
- **HTTP wrap** (existing = current concept HTTP routes only) -- rejected; MCP does not call Core routers, and many concepts already exist in-process without HTTP (hyperjump, diplomacy, visibility coverage, planet connections). Treating HTTP as the wrap boundary would shrink v1 to three HTTP families plus disk proximity and would force HTTP onto every later fill.
- **Gated plus selected fills** (fuel burn, mine-hit simulation, host-order timeline, battle odds in v1) -- rejected; closing those holes is the destination, not the first slice ([ADR 0016](0016-mcp-turninfo-fallback-and-disk-proximity.md)). They stay **MCP TurnInfo fallback** holes.
- **New helpers or newly wrapped concepts get Core HTTP in this map** -- rejected; changing the SPA is out of scope, and MCP does not use Core routers. Add HTTP later if a non-MCP consumer needs it.

## Consequences

- The v1 named-tool list may wrap in-process-only concepts without adding HTTP or new math.
- **MCP disk proximity** is a new Core product query (ships, planets, and cartography features in a light-year disk). Internal `iter_planets_within_radius` is planets-only and is not that query.
- Fuel burn, mine-hit simulation, host-order timeline, and battle odds are not v1 Core work.
- Later slices may gate additional fills; those fills remain Core **game concept**s.

Design index: [design-mcp.md](../design-mcp.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [Whether v1 MCP wraps only existing Core concepts or adds new query helpers](https://github.com/SteveDraper/Planets-Console/issues/321).
