# MCP adapter lives in `packages/mcp_adapter`

Status: accepted

The console needs an in-process [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28) surface on the existing FastAPI process ([Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310)). Transport is already Streamable HTTP on the root app ([MCP 2026-07-28 protocol and Python SDK for an in-process host](https://github.com/SteveDraper/Planets-Console/issues/311)). This ADR records **where the adapter lives** and **what it may import**.

The **MCP adapter** is a new workspace package `packages/mcp_adapter` (Python import `mcp_adapter`). It is a sibling of the **BFF**, not a layer inside Core or the BFF. Root `packages/server` mounts the SDK ASGI app at `/mcp` and runs `mcp.session_manager.run()` in the **root** lifespan (mounted sub-app lifespans do not run). The adapter is a thin transport: register tools, validate MCP-level input, call existing Core in-process APIs, return Core-shaped results. It owns no domain logic.

The Python project/import must not be named `mcp` -- that name is the official SDK (`from mcp.server import MCPServer`).

**`mcp_adapter` may import:** the official SDK `mcp`; Core in-process surfaces `api.services.*`, `api.concepts.*`, `api.analytics.catalog`, analytic **export query context** / registry, compute orchestrator **submit**, `api.errors`, and models/transport needed to call those.

**`mcp_adapter` must not import:** `bff.*` (SPA shaping); `api.storage.*`; Core FastAPI routers / `api.app` (no loopback HTTP); analytic compute internals; `api.handlers.*` (Core's HTTP adapter -- warp-well / cartography go through **concepts** / services).

**Who may import `mcp_adapter`:** root `server` only (mount + lifespan). Not Core, not BFF, not the frontend.

Human-parity for later tickets is **information** parity, not "return the BFF table/map JSON." If a shared wire shape is needed, extract it below both adapters.

No BFF HTTP export-query routes. No standalone MCP process.

## Considered options

- **Core (`packages/api`)** -- rejected; Core would learn a client protocol. Today it has no SPA knowledge; MCP is the same kind of leak.
- **BFF (`packages/bff`)** -- rejected; BFF is SPA-shaped and must not grow business logic or HTTP export-query routes. Mixing agent protocol with frontend shaping invites both.
- **Root server only (`packages/server`)** -- rejected; that package is a thin composition root. A full adapter there becomes a junk drawer. It still **mounts** `/mcp` and owns lifespan.
- **Workspace project named `mcp`** -- rejected; collides with the official SDK import.
- **Folder `mcp` / import `mcp_adapter`** -- rejected; existing packages match folder to import (`api`, `bff`, `server`).

## Consequences

- uv workspace gains a `mcp_adapter` member; `server` depends on it the way it depends on `api` and `bff`.
- Agent payloads are Core-shaped unless a later decision extracts a shared DTO below BFF and MCP.
- Glossary: **MCP adapter** in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md).

See also: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310), [Where the MCP adapter lives in the process](https://github.com/SteveDraper/Planets-Console/issues/315), [docs/research/mcp-2026-07-28-protocol.md](../research/mcp-2026-07-28-protocol.md).
