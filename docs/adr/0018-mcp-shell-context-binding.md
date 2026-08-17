# MCP binds shell context per call; login is a header

Status: accepted

Game, turn, and **perspective** on MCP must stay per-call and stateless, matching HTTP **shell context** and [ADR 0014](0014-mcp-login-identity-and-visibility.md) (no sticky MCP session). This ADR records how that tuple -- and the **MCP login identity** -- ride on the wire.

**MCP login identity** is an HTTP header on the call (client-pinned, still sent every request). The server **credential probe**s it and fails closed. It is not a tool argument and not `_meta`. The MCP client may send a different header on the next call; the server does not remember it. Protocol catalog methods (`server/discover`, `tools/list`) do not require the header.

**Shell context** is explicit tool arguments: **game id**, **turn**, and **perspective** (1-based slot, or `0` for spectator) -- not a **viewpoint** name. Turn-scoped tools require all three with no defaults. Game-scoped tools require game id only. Catalog/list tools need login only. Fields are flat and required per tool, not a partial nested object. Consecutive calls may name different **shell context**s. Not an MCP resource ([ADR 0017](0017-mcp-catalog-named-tools-and-export-hatch.md) is tools-only in v1) and not `_meta`.

## Considered options

- **All four as tool arguments** -- rejected; login is identity, not a gameplay question. Putting it on every schema invites the model to probe other stored names as if switching player were the query.
- **All four as HTTP headers** -- rejected; the advisor must change game, turn, and **perspective** (compare turns, switch slot on a finished game). Headers are client-config, not model-visible arguments.
- **All four in `_meta`** -- rejected; `_meta` is protocol metadata (`protocolVersion`, `clientInfo`). 2026-07-28's substitute for a session is an ordinary tool argument, not hidden transport state.
- **MCP resource as current context** -- rejected; v1 declares tools only ([ADR 0017](0017-mcp-catalog-named-tools-and-export-hatch.md)), and a current-context resource is session memory by another name.
- **Server `set_context` / opaque context id** -- rejected; hidden selection on the server. Same as the SPA anti-pattern.
- **Infer defaults** (omit turn → **GameInfo** max turn; omit **perspective** → login's slot) -- rejected; the server must not guess whose **TurnInfo** you meant.
- **Viewpoint name as the tool argument** -- rejected; **shell context** and Core already use **perspective**. Name→slot is SPA chrome. Spectator has no player name (`0`).

## Consequences

- The login header name is `X-Planets-Nu-Login`. Tool argument names for **shell context** are `game_id`, `turn`, `perspective` ([ADR 0022](0022-mcp-v1-named-tool-catalog.md)).
- How the MCP client sets the login header (v1 Cursor `mcp.json`) is [ADR 0023](0023-mcp-v1-client-connection.md).
- **Viewpoint eligibility** of the named **perspective** is [ADR 0019](0019-viewpoint-eligibility-in-core.md).
- Hatch query and ensure take the same **shell context** arguments as other turn-scoped tools; list is login-only ([ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md)).
- Glossary: **shell context**, **MCP login identity** in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [How MCP binds game, turn, and perspective](https://github.com/SteveDraper/Planets-Console/issues/318).
