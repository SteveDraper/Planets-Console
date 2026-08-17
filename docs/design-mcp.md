# Design: Agent MCP surface

**Status:** Accepted v1 design (tracer shipped: package, `/mcp` mount, login, `list_stored_games`)  
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

- Each call names an **MCP login identity** as the HTTP header `X-Planets-Nu-Login`. **Credential probe** fail-closed. No password on MCP. **Login exchange** stays on SPA/BFF. v1 Cursor packaging: [ADR 0023](adr/0023-mcp-v1-client-connection.md).
- Auth is login identity only. **Viewpoint** is not an MCP auth binding. The client may switch login identity per call. No MCP session.
- **MCP visibility ceiling** matches SPA **viewpoint eligibility** ([ADR 0019](adr/0019-viewpoint-eligibility-in-core.md)). Allowed **perspective**: that slot's **TurnInfo**, **GameInfo**, and analytics derived from them. Never another perspective's **TurnInfo** when eligibility would refuse that slot, never **account API key**s, never **compute diagnostics**. No **storage-only load** on MCP.

## Shell context binding

[How MCP binds game, turn, and perspective](https://github.com/SteveDraper/Planets-Console/issues/318). [ADR 0018](adr/0018-mcp-shell-context-binding.md).

- Split wire: **MCP login identity** is an HTTP header (client-pinned, still per request). Game id, turn, and **perspective** are tool arguments. Not `_meta`, not an MCP resource, no server memory of the selection.
- Always explicit: turn-scoped tools require the full **shell context** triple; game-scoped tools require game id; catalog/list tools need login only. No "latest turn" or "login's slot" inference. Flat required fields, not a partial nested object.
- The agent names **perspective** (1-based slot, or `0` for spectator), not a **viewpoint** name.

## Client connection (v1)

[How an MCP client connects in v1 (Cursor mcp.json vs in-app)](https://github.com/SteveDraper/Planets-Console/issues/326). [ADR 0023](adr/0023-mcp-v1-client-connection.md).

v1 documents Cursor desktop/CLI as the reference client. Any spec-compliant Streamable HTTP client may hit `/mcp` (with or without a trailing slash; the process rewrites `/mcp` to `/mcp/` so clients that do not follow POST redirects still reach Streamable HTTP). The console process must already be running (default bind `127.0.0.1:8000`). Cloud Agents are out of v1. Do not commit `.cursor/mcp.json`. Set `PLANETS_NU_LOGIN` in the environment, then copy into user `~/.cursor/mcp.json` or a local project file:

```json
{
  "mcpServers": {
    "planets-console": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "X-Planets-Nu-Login": "${env:PLANETS_NU_LOGIN}"
      }
    }
  }
}
```

A second identity is another server entry or a changed env var. v1 does not add CORS or a Vite Origin allowlist. An SPA-embedded advisor is a follow-on: [SPA-embedded advisor panel on the MCP surface](https://github.com/SteveDraper/Planets-Console/issues/329).

## Viewpoint eligibility

[Shared viewpoint eligibility below the SPA for MCP and the shell](https://github.com/SteveDraper/Planets-Console/issues/323). [ADR 0019](adr/0019-viewpoint-eligibility-in-core.md).

- Core `ViewpointEligibilityService.eligible_perspectives` (next to `GameService`) owns the allowed **perspective** set. MCP calls it in-process. Not `concepts/`, not BFF, not a copy inside `mcp_adapter`.
- XOR matching the SPA: live + player -> `{own slot}`; live + non-player -> `{0}`; finished -> `{1..N}`, no `0`.
- SPA consumes the set via BFF `GET /games/{game_id}/viewpoint-eligibility?username=` (JSON `perspectives`; login-keyed; refetch on identity switch) and applies chrome. **Storage-only load** stays SPA-only. Load-all's expected-perspective set is a different policy.

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

**Later, not never:** **load-all**; homeworld assertions/refresh; hull-mask edits; inference pause/recompute. Other collection-scan holes (minefields-in-disk, FC search, fuel, combat, host-order, planet reachability from an arbitrary map coordinate) stay holes under the fallback rule and are not v1 Core work ([ADR 0021](adr/0021-mcp-v1-wrap-existing-gated-fills.md), [ADR 0022](adr/0022-mcp-v1-named-tool-catalog.md)). Hatch query of incomplete/partial export trees with an explicit non-final indicator is later ([ADR 0020](adr/0020-mcp-export-hatch-describe-query-ensure.md)).

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
- **MCP shell tool**s are the same catalog, wrapping Core services rather than **game concept**s.
- The only generic hatch is the **MCP export query hatch** (JSONPath + scope over an **analytic export catalog**). Hatch tools, ensure, and no MCP streams: [ADR 0020](adr/0020-mcp-export-hatch-describe-query-ensure.md).
- Exact named-tool list: [Exact v1 named gameplay tool list](https://github.com/SteveDraper/Planets-Console/issues/324) / [ADR 0022](adr/0022-mcp-v1-named-tool-catalog.md) (next section).

---

## v1 named tool list

[Exact v1 named gameplay tool list](https://github.com/SteveDraper/Planets-Console/issues/324). [ADR 0022](adr/0022-mcp-v1-named-tool-catalog.md).

Argument names for **shell context**: `game_id`, `turn`, `perspective` (1-based slot, or `0` for spectator). No defaults. Login is the **MCP login identity** header, not a tool argument ([ADR 0018](adr/0018-mcp-shell-context-binding.md)).

**Scopes**

- Login only: no shell-context args
- Game: `game_id`
- Game+turn: `game_id`, `turn`
- Full **shell context**: `game_id`, `turn`, `perspective`

Turn-scoped tools do not auto-ensure. Missing stored turn: `unavailable` / `needs_ensure` (same as hatch query). Ineligible **perspective**: **viewpoint eligibility** refusal ([ADR 0019](adr/0019-viewpoint-eligibility-in-core.md)).

### MCP shell tools

| Tool | Scope | Extra args | Wraps |
|---|---|---|---|
| `list_stored_games` | Login only | -- | `GameService.list_stored_games` |
| `get_game_info` | Game | -- | `GameService.get_game_info` |
| `refresh_game_info` | Game | -- | `GameService.refresh_game_info` |
| `ensure_turn` | Full shell context | -- | `TurnLoadService.ensure_turn_loaded`. Returns `{ "status": "already_stored" \| "loaded" }` only -- never the **TurnInfo** body. Synchronous (waits for loadturn). |
| `list_stored_perspectives` | Game+turn | -- | `TurnLoadService.list_stored_turn_perspectives` |

### MCP named gameplay tools

| Tool | Scope | Extra args | Wraps |
|---|---|---|---|
| `point_in_warp_well` | Full shell context | `planet_id`, `x`, `y`, `well_kind` (`normal`/`hyperjump`) | `coordinate_in_warp_well` |
| `warp_well_cells` | Full shell context | `planet_id`, `well_kind` | `map_cell_indices_in_warp_well` |
| `flare_endpoints` | Login only | `x`, `y`, `warp_speed`, `movement_kind` (`regular`/`gravitonic`) | `flare_points_for_warp` plus origin (map endpoints, not raw offsets) |
| `sample_stellar_cartography` | Full shell context | `x`, `y` | `sample_at` |
| `stellar_cartography_summary` | Full shell context | -- | `stellar_cartography_turn_summary` |
| `disk_proximity` | Full shell context | `x`, `y`, `radius_ly`, optional `include` (`ships`/`planets`/`cartography`, repeatable; omit = all three) | **MCP disk proximity** (`api.concepts.disk_proximity.disk_proximity`). Hits: `kind`, `id`, `x`, `y`, plus radius when the feature is a disk. Cartography kinds on hits: `ion_storm`, `nebula`, `star_cluster`, `black_hole`, `wormhole`, `debris_disk`. Minefields are not in this result set. |
| `hyperjump_landing` | Full shell context | `ship_id` | `ship_is_performing_hyperjump`, `hyperjump_landing_xy`. `{ "jumping": false, "reason": ... }` or `{ "jumping": true, "x", "y" }`. Landing is **before warp-well snap**. The tool `description` must state that explicitly and nudge the agent to consider well pull via `point_in_warp_well` / `warp_well_cells`. |
| `distance_ly` | Login only | `x1`, `y1`, `x2`, `y2` | `nebula_visibility.distance_ly` |
| `reachable_planets` | Full shell context | `from_planet_id`, `warp_speed`, `gravitonic_movement`, `flare_mode` (`off`/`include`/`only`), optional `flare_depth` (default 1) | **Connections engine** (`connection_routes_with_options`), then keep routes where `from_planet_id` is an endpoint. No illustrative routes. No point-origin / ship-location args (later Core fill). |
| `get_ship` | Full shell context | `ship_id` | Named **TurnInfo** ship (whole entity) |
| `get_planet` | Full shell context | `planet_id` | Named **TurnInfo** planet (whole entity) plus optional starbase adjunct (`starbase: object \| null`). Locate the base by planet id, not RST `starbase.id`. `buildingstarbase` stays on the planet. No standalone `get_starbase`. |
| `get_minefield` | Full shell context | `minefield_id` | Named **TurnInfo** minefield |
| `get_ion_storm` | Full shell context | `ion_storm_id` | Named **TurnInfo** ion storm |
| `get_wormhole` | Full shell context | `wormhole_id` | Named **TurnInfo** wormhole |
| `get_player` | Full shell context | `player_id` (`Player.id`, not **perspective**) | Named **TurnInfo** player; strip `email` and `savekey` |

Fallback tools return the whole stored entity for that id in this **perspective**'s **TurnInfo**. Missing id: not found (absent from this RST, including fog). No list/search/filter tools.

Hatch tools (`list_analytic_exports`, `query_analytic_export`, `ensure_analytic_export`) are [ADR 0020](adr/0020-mcp-export-hatch-describe-query-ensure.md), not this table.

---

## Export query hatch

[How analytic exports and live analytics appear on MCP](https://github.com/SteveDraper/Planets-Console/issues/319). [ADR 0020](adr/0020-mcp-export-hatch-describe-query-ensure.md). Export Future MCP: [design-analytic-exports.md](design-analytic-exports.md).

v1 analytic *results* on MCP are this hatch plus **MCP named gameplay tool**s -- not table/map GET twins, not **table stream**s. Same materializers and catalog metadata; no second path.

- `list_analytic_exports` -- optional `analytic_id`; `detail=summary|full`. Omit id defaults to **MCP export catalog summary** for every analytic; named id defaults to full **analytic export catalog**. Omit-id + `detail=full` is refused (`catalog_too_broad`). Login only.
- `query_analytic_export` -- non-empty `paths` list (**batched export query**) + **shell context**; same result envelope as in-process. Does not admit new **analytic export ensure**. Materializes only persisted / ensure-final. Otherwise `unavailable` with `needs_ensure` or `in_progress` (plus existing reasons). Agent polls until `ok`. Successful payloads are capped by the **MCP hatch result budget**.
- `ensure_analytic_export` -- optional `dry_run` = **analytic export ensure probe**. Live call returns immediately `already_satisfied` or `accepted`. Admit is Core **analytic export ensure** in-process at `background` (orchestrator via [Export ensure + gap-fill migration](https://github.com/SteveDraper/Planets-Console/issues/204)); not a waiter, not a `ComputeRequest` tool, and not blocked on [Compute orchestrator (phase 3): uniform BFF compute API](https://github.com/SteveDraper/Planets-Console/issues/203). [How this MCP product relates to orchestrator phase 3](https://github.com/SteveDraper/Planets-Console/issues/320). No MCP Tasks in v1.

## Result size and query cost

[MCP pagination, result size, and query-cost controls](https://github.com/SteveDraper/Planets-Console/issues/327). [ADR 0024](adr/0024-mcp-result-size-and-query-cost.md).

v1 does not declare MCP protocol pagination (list operations only; `tools/call` is not paged).

**MCP shell tool**s, **MCP named gameplay tool**s, and **MCP TurnInfo fallback** have no extra cap, pagination, or truncation. `ensure_turn` stays synchronous loadturn.

Hatch query dialect is Core's JSONPath subset (`$`, dotted names, `[index]`, `[*]`). No slices or filters. Top-K is a batched index list (`$.solutions[0]` .. `[K-1]`). After Core `ok`, the adapter enforces **MCP hatch result budget** (65536 UTF-8 bytes of the serialized success envelope). Over budget: `isError`, `reason: "result_too_large"`, `bytes`, `budget_bytes`, narrowing hint, zero path values -- not Core `unavailable`. Empty `paths` is invalid input. No separate max-path-count.

Live hatch ensure does not wait. Descriptions tell the agent to `dry_run` first; the protocol does not enforce it. No extra timeout, threshold, or concurrent-root cap.

---

## Testing and contract

[MCP testing and contract strategy](https://github.com/SteveDraper/Planets-Console/issues/328). [ADR 0025](adr/0025-mcp-testing-and-contract.md).

v1 does not add OpenAPI for `/mcp`. The contract is SDK tool registration: `server/discover` plus `tools/list` input schemas. Tests lock the exact v1 name set (5 **MCP shell tool**s + 15 **MCP named gameplay tool**s + 3 hatch tools) and required input properties. Do not freeze free-text `description`s except ADR-mandated phrases (`hyperjump_landing` pre-well-snap nudge; ensure `dry_run` first). Hatch value trees stay Core **analytic export catalog** goldens.

**Layers**

- `packages/api` -- **analytic export hatch-read** (`AnalyticQueryContext.hatch_read`: ensure-final materialize; `unavailable` with `needs_ensure` / `in_progress`); fixture alpha/beta gates; `ctx.query` still admits ensure. Concept math, including **MCP disk proximity**, stays here.
- `packages/mcp_adapter` -- in-process tool handlers (not HTTP). Wrap mapping only. Catalog name/inputSchema lock. Thin equality of `query_analytic_export` to `AnalyticQueryContext.hatch_read` (one fixture case plus **connections**). Adapter-only errors: `result_too_large`, `catalog_too_broad`, missing **MCP login identity**, missing **shell context**, **viewpoint eligibility** refuse.
- `packages/server` -- thin Streamable HTTP smoke: `POST /mcp` `server/discover` is tools-only, root `session_manager` lifespan, Origin 403, login fail-closed. Not one HTTP test per tool.

**Hatch parity**

MCP `query_analytic_export` matches `AnalyticQueryContext.hatch_read` when the scope is persisted / ensure-final -- same registry, same JSONPath, same `ok` / `value`. It does **not** equal `ctx.query` (that path admits ensure). When not final, MCP returns `needs_ensure` or `in_progress`; Core tests own that gate. Over **MCP hatch result budget** is an adapter error with zero path values, not Core `unavailable`. `ensure_analytic_export` `dry_run` matches **analytic export ensure probe**; live returns `already_satisfied` | `accepted` and does not wait.

**Make targets**

- `test_mcp_adapter` -- `packages/mcp_adapter/tests`; wired into `test`, `ci`, and `ci_full`
- `test_server` -- existing; HTTP smoke lives here
- `lint` -- include `packages/mcp_adapter`
