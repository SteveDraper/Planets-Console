# Design: Agent MCP surface

**Status:** Wayfinding (decisions land here as map tickets resolve; not an implementation brief yet)  
**Map:** [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310)  
**Spec:** [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)  
**Glossary:** [CONTEXT.md](../CONTEXT.md)

Write path / submitting orders is out of scope. Same host, new endpoint(s), not a standalone process.

---

## Transport

[MCP 2026-07-28 protocol and Python SDK for an in-process host](https://github.com/SteveDraper/Planets-Console/issues/311). Findings: [mcp-2026-07-28-protocol.md](research/mcp-2026-07-28-protocol.md).

Streamable HTTP on the existing root FastAPI process via `mcp` 2.0.0. OAuth 2.1 is optional for localhost; bind plus Origin validation remain the network floor. Tools are the primary surface.

---

## Adapter package and layer

[Where the MCP adapter lives in the process](https://github.com/SteveDraper/Planets-Console/issues/315). [ADR 0015](adr/0015-mcp-adapter-package.md).

- New workspace package `packages/mcp_adapter` (import `mcp_adapter`), sibling of the **BFF**. Root `server` mounts Streamable HTTP at `/mcp` and runs `mcp.session_manager.run()` in the root lifespan.
- Thin transport over Core in-process APIs. Must not import `bff.*`, storage, Core routers/`api.app`, analytic compute internals, or `api.handlers.*`. Only `server` may import `mcp_adapter`.
- Do not name the Python package `mcp` (SDK import clash). Human-parity is information parity, not BFF JSON.

---

## Auth and identity

[How an MCP agent authenticates and which identity it acts as](https://github.com/SteveDraper/Planets-Console/issues/314). [ADR 0014](adr/0014-mcp-login-identity-and-visibility.md).

- Each call names an **MCP login identity**. **Credential probe** fail-closed. No password on MCP. **Login exchange** stays on SPA/BFF.
- Auth is login identity only. **Viewpoint** is not an MCP auth binding. The client may switch login identity per call. No MCP session.
- **MCP visibility ceiling** matches SPA **viewpoint** eligibility. Allowed **perspective**: that slot's **TurnInfo**, **GameInfo**, and analytics derived from them. Never another perspective's **TurnInfo** when the SPA would hide it, never **account API key**s, never **compute diagnostics**. No **storage-only load** on MCP.

How game, turn, and perspective (and the login name on the wire) are bound: [How MCP binds game, turn, and perspective](https://github.com/SteveDraper/Planets-Console/issues/318). Must stay per-call and stateless.

Shared eligibility rule (today SPA-only): [Shared viewpoint eligibility below the SPA for MCP and the shell](https://github.com/SteveDraper/Planets-Console/issues/323).

---

## First-slice human-parity

[What human-parity means for the first MCP slice](https://github.com/SteveDraper/Planets-Console/issues/316). [ADR 0016](adr/0016-mcp-turninfo-fallback-and-disk-proximity.md). Inventory: [console-human-visible-surfaces.md](research/console-human-visible-surfaces.md).

v1 is read-only advisor information at human *analysis* parity -- not every SPA pixel, not BFF table/map JSON.

**In v1**

- Stored-game list, **GameInfo** (stored + refresh), **turn-ensure**, stored perspectives
- All catalog analytics' *information*: **base-map**, **scores**, **connections**, **stellar-cartography**, **fleet**, **visibility**, **homeworld-locator**
- All existing concept HTTP, including warp-well point/cells and flare points
- Stored **TurnInfo** as **MCP TurnInfo fallback** (named-object fields only; MCP descriptions steer to distilled queries)
- **MCP disk proximity** (ships, planets, and cartography features within X ly of a coordinate). Core has no such product query today; wrap-only cannot close the gap ([Whether v1 MCP wraps only existing Core concepts or adds new query helpers](https://github.com/SteveDraper/Planets-Console/issues/321))

**Out of this map's MCP:** operator diagnostics (request trees, solver telemetry, compute freeze); **login exchange**, passwords, and credential management (already [ADR 0014](adr/0014-mcp-login-identity-and-visibility.md)).

**Later, not never:** **load-all**; homeworld assertions/refresh; hull-mask edits; inference pause/recompute. Other collection-scan holes (minefields-in-disk, FC search, fuel, combat) stay holes under the fallback rule but are not v1 gates.

**Not this section:** catalog shape ([MCP catalog shape: named gameplay tools vs generic query vs resources](https://github.com/SteveDraper/Planets-Console/issues/317)); stream and trigger-vs-persisted compute ([How analytic exports and live analytics appear on MCP](https://github.com/SteveDraper/Planets-Console/issues/319)).
