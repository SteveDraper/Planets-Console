# v1 MCP client is Cursor mcp.json on localhost

Status: accepted

v1 agents reach the Planets Console MCP surface over Streamable HTTP at `/mcp` on the already-running process ([MCP 2026-07-28 protocol and Python SDK for an in-process host](https://github.com/SteveDraper/Planets-Console/issues/311), [ADR 0015](0015-mcp-adapter-package.md)). **MCP login identity** is already an HTTP header, not a tool argument ([ADR 0014](0014-mcp-login-identity-and-visibility.md), [ADR 0018](0018-mcp-shell-context-binding.md)). This ADR records the documented v1 client and how that header is packaged.

v1 documents Cursor desktop/CLI via `mcp.json` as the reference client. The example URL is `http://127.0.0.1:8000/mcp` (default `ServerConfig` bind). The console process must already be running -- Streamable HTTP does not spawn it. Any spec-compliant Streamable HTTP client may connect; Cursor is what v1 writes down. Copy-pasteable `mcp.json` lives in [design-mcp.md](../design-mcp.md). Do not commit `.cursor/mcp.json`.

The documented server entry sends `X-Planets-Nu-Login: ${env:PLANETS_NU_LOGIN}`. One entry; a second identity is another server entry or a changed env var. The value is a planets.nu account name, not a token -- not `Authorization` Bearer. Catalog methods still omit the header ([ADR 0018](0018-mcp-shell-context-binding.md)). Cursor Cloud Agents are out of v1 (they cannot reach loopback). v1 does not add CORS or a Vite Origin allowlist on `/mcp`.

An SPA-embedded advisor panel is a follow-on product, not this map: [SPA-embedded advisor panel on the MCP surface](https://github.com/SteveDraper/Planets-Console/issues/329).

## Considered options

- **SPA-embedded advisor in v1** -- rejected; this map does not change the SPA as a requirement. Follow-on is [SPA-embedded advisor panel on the MCP surface](https://github.com/SteveDraper/Planets-Console/issues/329).
- **Both Cursor and SPA in v1** -- rejected; same SPA cost as embedding the panel now.
- **Commit `.cursor/mcp.json`** -- rejected; a project MCP server is red whenever the console is not running, and a login name is per-operator. Same pattern as GitHub MCP docs in this repo (`docs/cursor-github-setup.md`).
- **Literal login name in the documented `mcp.json`** -- rejected; env interpolation keeps the example identity-free.
- **Two named server entries from day one** -- rejected as a v1 ship requirement; docs note the second-entry pattern.
- **Cloud Agents / remote bind in v1** -- rejected; would reopen OAuth and non-localhost ([ADR 0014](0014-mcp-login-identity-and-visibility.md), protocol ticket).

## Consequences

- Glossary **MCP login identity** names the header `X-Planets-Nu-Login` in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md).
- [ADR 0018](0018-mcp-shell-context-binding.md) client-packaging pointer lands here.

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [How an MCP client connects in v1 (Cursor mcp.json vs in-app)](https://github.com/SteveDraper/Planets-Console/issues/326).
