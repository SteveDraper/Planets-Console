# MCP login identity and visibility ceiling

Status: accepted

A local MCP surface on the Planets Console process needs a Planets.nu identity without inventing a second credential type or a protocol session. OAuth 2.1 is optional for localhost ([MCP 2026-07-28 protocol and Python SDK for an in-process host](https://github.com/SteveDraper/Planets-Console/issues/311)); this ADR records the application identity on top of that floor.

## Decision

- Each MCP call names an **MCP login identity** (planets.nu account name). The server **credential probe**s that name and fails closed. No OAuth, no extra MCP secret, no password on MCP. **Login exchange** stays on the SPA/BFF path ([ADR 0007](0007-account-api-key-and-silent-login.md)).
- Auth is **login identity** only. **Viewpoint** is not an MCP auth binding; it is **shell context** ([How MCP binds game, turn, and perspective](https://github.com/SteveDraper/Planets-Console/issues/318)). The client may name a different login identity on the next call. MCP is per-request: no sticky MCP session.
- **MCP visibility ceiling:** the same **viewpoint** eligibility as the SPA for that login (in-progress: own slot or spectator; finished: all slots). For an allowed **perspective**: that slot's **TurnInfo**, **GameInfo**, and analytics derived from them. Never another perspective's **TurnInfo** when the SPA would disable that viewpoint, never **account API key** material, never **compute diagnostics**. MCP has no **storage-only load** path.

## Considered options

- **OAuth 2.1 on localhost** -- rejected; the protocol ticket already skips it for a single-user local server.
- **Extra shared secret in `mcp.json`** -- rejected; anyone who can hit the local port can already name a stored login on the BFF. A second secret does not change that trust model.
- **Password or login exchange on MCP** -- rejected for v1; passwords must not be persisted, and the SPA/BFF exchange path already exists. Cursor-only bootstrap can be added later without changing identity.
- **Viewpoint as auth binding** -- rejected; duplicates shell context and fights per-request MCP.
- **Sticky login for an invented MCP session** -- rejected; 2026-07-28 is per-request, and the server stays stateless per HTTP request.
- **Stricter than the SPA** (own slot even after the game finishes) -- rejected; finished-game review is human-parity.
- **Looser than the SPA** (any stored perspective while the game is live) -- rejected; on-disk opponent **TurnInfo** would leak past the human app.

## Consequences

- How the login name rides on the wire (tool argument vs header vs `_meta`) is decided with game/turn/perspective binding, and must stay per-call.
- Viewpoint eligibility today lives only in the SPA (`deriveShellViewpoints`). MCP cannot import that. Follow-on: [Shared viewpoint eligibility below the SPA for MCP and the shell](https://github.com/SteveDraper/Planets-Console/issues/323).
- Glossary: **MCP login identity**, **MCP visibility ceiling** in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [How an MCP agent authenticates and which identity it acts as](https://github.com/SteveDraper/Planets-Console/issues/314).
