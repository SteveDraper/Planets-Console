# mcp_adapter

In-process [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28) adapter for Planets Console.

Root `packages/server` mounts Streamable HTTP at **`/mcp`** and runs the SDK session manager in the **root** lifespan. This package owns tool registration and MCP-level validation; it calls Core services in-process and owns no domain logic.

Python import is `mcp_adapter` (not `mcp` -- that name is the official SDK).

Cursor `mcp.json` and the v1 catalog: [design-mcp.md](../../docs/design-mcp.md). Do not commit `.cursor/mcp.json`.
