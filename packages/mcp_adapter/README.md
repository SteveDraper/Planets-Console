# mcp_adapter

In-process [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28) adapter for Planets Console.

Root `packages/server` mounts Streamable HTTP at **`/mcp`** and runs the SDK session manager in the **root** lifespan. This package owns tool registration and MCP-level validation; it calls Core services in-process and owns no domain logic. The shipped catalog is the five **MCP shell tool**s (`list_stored_games`, `get_game_info`, `refresh_game_info`, `ensure_turn`, `list_stored_perspectives`), fifteen **MCP named gameplay tool**s (nine Core `api/concepts/` wraps and six **MCP TurnInfo fallback** tools), and three **MCP export query hatch** tools (`list_analytic_exports`, `query_analytic_export`, `ensure_analytic_export`).

Python import is `mcp_adapter` (not `mcp` -- that name is the official SDK).

Cursor `mcp.json` and the v1 catalog: [design-mcp.md](../../docs/design-mcp.md). Do not commit `.cursor/mcp.json`.
