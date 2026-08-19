# mcp_adapter

In-process [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28) adapter for Planets Console.

Root `packages/server` mounts Streamable HTTP at **`/mcp`** and runs the SDK session manager in the **root** lifespan. This package owns tool registration and MCP-level validation; it calls Core services in-process and owns no domain logic. The shipped catalog is the five **MCP shell tool**s (`list_stored_games`, `get_game_info`, `refresh_game_info`, `ensure_turn`, `list_stored_perspectives`) plus fifteen **MCP named gameplay tool**s: nine Core `api/concepts/` wraps (`point_in_warp_well`, `warp_well_cells`, `flare_endpoints`, `sample_stellar_cartography`, `stellar_cartography_summary`, `disk_proximity`, `hyperjump_landing`, `distance_ly`, `reachable_planets`) and six **MCP TurnInfo fallback** tools (`get_ship`, `get_planet`, `get_minefield`, `get_ion_storm`, `get_wormhole`, `get_player`). The export hatch is a later slice.

Python import is `mcp_adapter` (not `mcp` -- that name is the official SDK).

Cursor `mcp.json` and the v1 catalog: [design-mcp.md](../../docs/design-mcp.md). Do not commit `.cursor/mcp.json`.
