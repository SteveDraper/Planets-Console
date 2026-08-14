# Design: Agent MCP surface

**Status:** Wayfinding (decisions land here as map tickets resolve; not an implementation brief yet)  
**Map:** [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310)  
**Spec:** [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)  
**Glossary:** [CONTEXT.md](../CONTEXT.md)

Write path / submitting orders is out of scope. Same host, new endpoint(s), not a standalone process.

---

## Transport

[MCP 2026-07-28 protocol and Python SDK for an in-process host](https://github.com/SteveDraper/Planets-Console/issues/311). Findings: [mcp-2026-07-28-protocol.md](research/mcp-2026-07-28-protocol.md).

Streamable HTTP on the existing root FastAPI process via `mcp` 2.0.0. OAuth 2.1 is optional for localhost; bind plus Origin validation remain the network floor. Tools are the primary surface. Catalog shape of those tools: [ADR 0017](adr/0017-mcp-catalog-named-tools-and-export-hatch.md).

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
- **MCP visibility ceiling** matches SPA **viewpoint eligibility** ([ADR 0019](adr/0019-viewpoint-eligibility-in-core.md)). Allowed **perspective**: that slot's **TurnInfo**, **GameInfo**, and analytics derived from them. Never another perspective's **TurnInfo** when eligibility would refuse that slot, never **account API key**s, never **compute diagnostics**. No **storage-only load** on MCP.

## Shell context binding

[How MCP binds game, turn, and perspective](https://github.com/SteveDraper/Planets-Console/issues/318). [ADR 0018](adr/0018-mcp-shell-context-binding.md).

- Split wire: **MCP login identity** is an HTTP header (client-pinned, still per request). Game id, turn, and **perspective** are tool arguments. Not `_meta`, not an MCP resource, no server memory of the selection.
- Always explicit: turn-scoped tools require the full **shell context** triple; game-scoped tools require game id; catalog/list tools need login only. No "latest turn" or "login's slot" inference. Flat required fields, not a partial nested object.
- The agent names **perspective** (1-based slot, or `0` for spectator), not a **viewpoint** name.

## Viewpoint eligibility

[Shared viewpoint eligibility below the SPA for MCP and the shell](https://github.com/SteveDraper/Planets-Console/issues/323). [ADR 0019](adr/0019-viewpoint-eligibility-in-core.md).

- Core service next to `GameService` owns the allowed **perspective** set. MCP calls it in-process. Not `concepts/`, not BFF, not a copy inside `mcp_adapter`.
- XOR matching the SPA: live + player -> `{own slot}`; live + non-player -> `{0}`; finished -> `{1..N}`, no `0`.
- SPA consumes the set via the BFF (login-keyed; refetch on identity switch) and applies chrome. **Storage-only load** stays SPA-only. Load-all's expected-perspective set is a different policy.

---

## First-slice human-parity

[What human-parity means for the first MCP slice](https://github.com/SteveDraper/Planets-Console/issues/316). [ADR 0016](adr/0016-mcp-turninfo-fallback-and-disk-proximity.md). Inventory: [console-human-visible-surfaces.md](research/console-human-visible-surfaces.md).

v1 is read-only advisor information at human *analysis* parity -- not every SPA pixel, not BFF table/map JSON.

**In v1**

- Stored-game list, **GameInfo** (stored + refresh), **turn-ensure**, stored perspectives
- All catalog analytics' *information*: **base-map**, **scores**, **connections**, **stellar-cartography**, **fleet**, **visibility**, **homeworld-locator**
- All existing concept HTTP, including warp-well point/cells and flare points
- Stored **TurnInfo** as **MCP TurnInfo fallback** (named-object fields only; MCP descriptions steer to distilled queries)
- **MCP disk proximity** (ships, planets, and cartography features within X ly of a coordinate) -- the only new Core helper in v1 ([ADR 0021](adr/0021-mcp-v1-wrap-existing-gated-fills.md))

**Out of this map's MCP:** operator diagnostics (request trees, solver telemetry, compute freeze); **login exchange**, passwords, and credential management (already [ADR 0014](adr/0014-mcp-login-identity-and-visibility.md)).

**Later, not never:** **load-all**; homeworld assertions/refresh; hull-mask edits; inference pause/recompute. Other collection-scan holes (minefields-in-disk, FC search, fuel, combat, host-order) stay holes under the fallback rule and are not v1 Core work ([ADR 0021](adr/0021-mcp-v1-wrap-existing-gated-fills.md)). Hatch query of incomplete/partial export trees with an explicit non-final indicator is later ([ADR 0020](adr/0020-mcp-export-hatch-describe-query-ensure.md)).

---

## v1 wrap vs new Core helpers

[Whether v1 MCP wraps only existing Core concepts or adds new query helpers](https://github.com/SteveDraper/Planets-Console/issues/321). [ADR 0021](adr/0021-mcp-v1-wrap-existing-gated-fills.md).

- Wrap means the query math already lives in `api/concepts/` (HTTP or not). A new **MCP named gameplay tool** over an in-process-only concept is a wrap, not a fill.
- New Core helper only when a v1 gate requires it. Today that is **MCP disk proximity** alone.
- Filling a gap is a Core **game concept**, never `mcp_adapter` math.
- This map does not add concept HTTP. MCP calls Core in-process.

---

## Catalog shape

[MCP catalog shape: named gameplay tools vs generic query vs resources](https://github.com/SteveDraper/Planets-Console/issues/317). [ADR 0017](adr/0017-mcp-catalog-named-tools-and-export-hatch.md).

v1 declares **tools only** -- no MCP `resources`, no `prompts`. `server/discover` must not advertise capabilities we do not implement.

- **MCP named gameplay tool**s are the advisor API. Names and arguments are the question the agent asks (wrapping Core), not 1:1 HTTP twins and not family mega-tools with a `kind` enum. Descriptions are written for an agent that already understands Planets.nu: when to use the tool, when to prefer it over **MCP TurnInfo fallback**.
- The only generic hatch is the **MCP export query hatch** (JSONPath + scope over an **analytic export catalog**). Hatch tools, ensure, and no MCP streams: [ADR 0020](adr/0020-mcp-export-hatch-describe-query-ensure.md).
- Exact named-tool list: [Exact v1 named gameplay tool list](https://github.com/SteveDraper/Planets-Console/issues/324).

---

## Export query hatch

[How analytic exports and live analytics appear on MCP](https://github.com/SteveDraper/Planets-Console/issues/319). [ADR 0020](adr/0020-mcp-export-hatch-describe-query-ensure.md). Export Future MCP: [design-analytic-exports.md](design-analytic-exports.md).

v1 analytic *results* on MCP are this hatch plus **MCP named gameplay tool**s -- not table/map GET twins, not **table stream**s. Same materializers and catalog metadata; no second path.

- `list_analytic_exports` -- optional `analytic_id`; `detail=summary|full`. Omit id defaults to **MCP export catalog summary** for every analytic; named id defaults to full **analytic export catalog**. Login only.
- `query_analytic_export` -- JSONPath + **shell context**; same result envelope as in-process. Does not admit new **analytic export ensure**. Materializes only persisted / ensure-final. Otherwise `unavailable` with `needs_ensure` or `in_progress` (plus existing reasons). Agent polls until `ok`.
- `ensure_analytic_export` -- optional `dry_run` = **analytic export ensure probe**. Live call returns immediately `already_satisfied` or `accepted`. Admit is Core **analytic export ensure** in-process (orchestrator via [Export ensure + gap-fill migration](https://github.com/SteveDraper/Planets-Console/issues/204)); not a `ComputeRequest` tool and not blocked on [Compute orchestrator (phase 3): uniform BFF compute API](https://github.com/SteveDraper/Planets-Console/issues/203). [How this MCP product relates to orchestrator phase 3](https://github.com/SteveDraper/Planets-Console/issues/320). No MCP Tasks in v1.
