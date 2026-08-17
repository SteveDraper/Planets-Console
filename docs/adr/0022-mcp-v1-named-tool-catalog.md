# v1 MCP tools are shell, named gameplay, and the export hatch

Status: accepted

The exact v1 catalog is three classes of MCP tools: **MCP shell tool**s (stored games, **GameInfo**, **turn-ensure**, stored perspectives), **MCP named gameplay tool**s (concept wraps, **MCP disk proximity**, **MCP TurnInfo fallback**), and the already-named **MCP export query hatch**. Names and arguments live in [design-mcp.md](../design-mcp.md). Hatch names are not re-litigated ([ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md)).

Shell operations wrap Core services, not `api/concepts/`, so they are not **MCP named gameplay tool**s. GameInfo is two tools (stored vs **game info refresh**). **Turn-ensure** returns `already_stored` | `loaded` and never the **TurnInfo** blob; other turn-scoped tools do not auto-ensure (`unavailable` / `needs_ensure`, same as hatch query). Fallback is one tool per named family (`get_ship`, `get_planet`, `get_minefield`, `get_ion_storm`, `get_wormhole`, `get_player`), not a `kind` enum. A starbase is an optional adjunct on `get_planet` keyed by planet id -- RST `starbase.id` is not a player-facing handle. `hyperjump_landing` is pre-well-snap; the tool description must say so and nudge well pull via `point_in_warp_well` / `warp_well_cells`. `reachable_planets` is from a planet id only; reachability from an arbitrary map coordinate (ship location) is a later Core fill.

## Considered options

- **Call shell operations named gameplay tools** -- rejected; the glossary wrap is a **game concept**, and list-games is not one.
- **One `get_named_object(kind, id)` fallback** -- rejected; [ADR 0017](0017-mcp-catalog-named-tools-and-export-hatch.md) forbids family mega-tools with a `kind` enum.
- **`get_starbase` keyed by RST `starbase.id`** -- rejected; players and Console analytics locate a base by planet; sample RST `id` values are not the planet id.
- **Point-origin `reachable_planets` in v1** -- rejected; the **Connections engine** is planet-pair only. A coordinate origin would be new Core math ([ADR 0021](0021-mcp-v1-wrap-existing-gated-fills.md)).
- **Hyperjump landing after well snap** -- rejected; Core `hyperjump_landing_xy` is pre-snap. The tool must not silently snap; the description must tell the agent to consider wells.

## Consequences

- Glossary: **MCP shell tool**. Design index: [design-mcp.md](../design-mcp.md).
- Point-origin planet reachability stays a later hole, next to minefields-in-disk / fuel / combat.

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [Exact v1 named gameplay tool list](https://github.com/SteveDraper/Planets-Console/issues/324).
