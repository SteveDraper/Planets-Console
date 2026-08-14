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

- Exact header string and argument names are implementation.
- How the MCP client sets the login header (`mcp.json` vs in-app) remains the map's client connection story -- not this ADR.
- **Viewpoint eligibility** of the named **perspective** is [ADR 0019](0019-viewpoint-eligibility-in-core.md).
- The **MCP export query hatch** takes the same **shell context** arguments as other turn-scoped tools ([How analytic exports and live analytics appear on MCP](https://github.com/SteveDraper/Planets-Console/issues/319)).
- Glossary: **shell context**, **MCP login identity** in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [How MCP binds game, turn, and perspective](https://github.com/SteveDraper/Planets-Console/issues/318).
