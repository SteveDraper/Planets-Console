# MCP login identity and visibility ceiling

Status: accepted

A local MCP surface on the Planets Console process needs a Planets.nu identity without inventing a second credential type or a protocol session. OAuth 2.1 is optional for localhost ([MCP 2026-07-28 protocol and Python SDK for an in-process host](https://github.com/SteveDraper/Planets-Console/issues/311)); this ADR records the application identity on top of that floor.

## Decision

- Each MCP call names an **MCP login identity** (planets.nu account name). The server **credential probe**s that name and fails closed. No OAuth, no extra MCP secret, no password on MCP. **Login exchange** stays on the SPA/BFF path ([ADR 0007](0007-account-api-key-and-silent-login.md)).
- Auth is **login identity** only. **Viewpoint** is not an MCP auth binding; it is **shell context** ([ADR 0018](0018-mcp-shell-context-binding.md)). The client may send a different login header on the next call. MCP is per-request: no sticky MCP session.
- **MCP visibility ceiling:** the same **viewpoint eligibility** as the SPA for that login ([ADR 0019](0019-viewpoint-eligibility-in-core.md)): in-progress XOR (player -> own slot; non-player -> spectator `0`); finished -> all player slots `1..N`, not `0`. For an allowed **perspective**: that slot's **TurnInfo**, **GameInfo**, and analytics derived from them. Never another perspective's **TurnInfo** when eligibility would refuse that slot, never **account API key** material, never **compute diagnostics**. MCP has no **storage-only load** path.

## Considered options

- **OAuth 2.1 on localhost** -- rejected; the protocol ticket already skips it for a single-user local server.
- **Extra shared secret in `mcp.json`** -- rejected; anyone who can hit the local port can already name a stored login on the BFF. A second secret does not change that trust model.
- **Password or login exchange on MCP** -- rejected for v1; passwords must not be persisted, and the SPA/BFF exchange path already exists. Cursor-only bootstrap can be added later without changing identity.
- **Viewpoint as auth binding** -- rejected; duplicates shell context and fights per-request MCP.
- **Sticky login for an invented MCP session** -- rejected; 2026-07-28 is per-request, and the server stays stateless per HTTP request.
- **Stricter than the SPA** (own slot even after the game finishes) -- rejected; finished-game review is human-parity.
- **Looser than the SPA** (any stored perspective while the game is live) -- rejected; on-disk opponent **TurnInfo** would leak past the human app.

## Consequences

- The login name rides as the HTTP header `X-Planets-Nu-Login`, not a tool argument or `_meta` ([ADR 0018](0018-mcp-shell-context-binding.md)). v1 Cursor packaging: [ADR 0023](0023-mcp-v1-client-connection.md).
- **Viewpoint eligibility** is a Core service; the SPA consumes it via the BFF ([ADR 0019](0019-viewpoint-eligibility-in-core.md)).
- Glossary: **MCP login identity**, **MCP visibility ceiling**, **viewpoint eligibility** in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [How an MCP agent authenticates and which identity it acts as](https://github.com/SteveDraper/Planets-Console/issues/314).
