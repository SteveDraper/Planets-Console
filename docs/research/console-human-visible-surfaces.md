# Human-visible Console surfaces (inventory)

Research for [Inventory of human-visible Console surfaces an MCP must match](https://github.com/SteveDraper/Planets-Console/issues/313). Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310).

**Verified:** 2026-08-13 against `packages/frontend/src/api/`, `packages/bff/bff/routers/`, `packages/api/api/routers/`, and [`docs/user-guide.md`](../user-guide.md).

This document lists **existing Console HTTP surfaces** the SPA uses (or that exist as query-shaped counterparts to what the SPA shows). It does **not** propose MCP tools, resources, or prompts.

---

## How to read this catalog

The SPA talks **only to the BFF** (`/bff/...`). The BFF calls Core **in-process** via `CoreClient` (not a second HTTP hop). Core REST (`/api/v1/...`) is the same business surface, used by tests and any non-SPA client. Where both exist, they are **one capability with two URLs**.

**Columns**

| Column | Meaning |
|--------|---------|
| **Route** | Public path as mounted on the root process. BFF paths are what the browser calls. |
| **Layer** | BFF (SPA-facing) or Core (domain). |
| **SPA** | Whether `packages/frontend` calls this path today. |
| **Returns** | Response shape the human UI consumes. |
| **Turn ensure** | Whether the call can fetch a missing turn from Planets.nu (`loadturn`). |
| **Compute** | Whether the call runs the **compute orchestrator** (durable analytic work) vs a sync projection from stored `TurnInfo`. |

**Turn ensure vs compute** are independent. Ensure loads raw game state into storage. Compute derives analytics (fleet ledgers, scores inference, homeworld layout) from stored turns.

**Not in this inventory**

- Core `GET/PUT/POST/DELETE /api/v1/store/{path}` -- storage CRUD, not a Console UI surface.
- Process health (`GET /health`, `GET /bff/health`, `GET /api/health`).
- Analytic **export query HTTP** -- not implemented on BFF (deferred; see map Out of scope).
- Client-only chrome with no extra HTTP: map pan/zoom/scale, Map options planet labels, shell error bar, analytic enablement persisted in the browser.

---

## Human UI to HTTP

From [`docs/user-guide.md`](../user-guide.md) and the SPA clients:

| UI region | What the human does | HTTP the SPA uses |
|-----------|---------------------|-------------------|
| Header login | Set / change planets.nu identity | `GET/POST/DELETE /bff/credentials/...` |
| Header game | List stored games, add/select, refresh info | `GET /bff/games`, `GET/POST /bff/games/{id}/info` |
| Header turn / viewpoint | Choose year and perspective slot | `GET .../stored-perspectives`; `POST .../turns/ensure`; optional load-all |
| Shell first paint | Optional default game; compute-diagnostics flag | `GET /bff/shell/bootstrap` |
| Analytics sidebar | Catalog of toggleable analytics | `GET /bff/analytics` |
| Tabular main | Stacked tiles per enabled table analytic | `GET /bff/analytics/{id}/table` plus scores/fleet streams |
| Map main | Base planets + enabled map layers | `GET /bff/analytics/{id}/map` plus cartography sample/summary |
| Scores extras | Inference column, hull mask, pause, recompute | `/bff/analytics/scores/inference/...` |
| Fleet extras | Live ledger stream, hull/engine names | `/bff/analytics/fleet/table-stream`, `.../component-catalog` |
| Homeworld extras | Candidates, assertions, refresh | map/table GET plus `POST .../assertions`, `POST .../refresh` |
| Diagnostics modal | Request trees, scores dump, homeworld solver, compute freeze | `/bff/diagnostics/...` (operator, not analysis) |

Shell **scope** the human sets once: `{gameId, turn, perspective}` plus login `username`. Almost every analytic call repeats that triple as query params. Core counterparts encode it in the path: `/api/v1/games/{game_id}/{perspective}/turns/{turn_number}/...`.

---

## 1. Shell, credentials, games, turns

### 1.1 Credentials / login

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/credentials/probe?username=` | BFF | Yes (login) | `{present: bool}` -- decryptable account API key on disk | No (no Planets.nu) | No |
| `POST /bff/credentials/exchange` | BFF | Yes (login) | `{ok: true}` after Planets.nu login; stores obfuscated account API key | No | No |
| `DELETE /bff/credentials/{username}` | BFF | Yes (change login) | 204 | No | No |
| `GET /api/v1/credentials/probe` | Core | No | Same as BFF | No | No |
| `POST /api/v1/credentials/exchange` | Core | No | Same as BFF | No | No |
| `DELETE /api/v1/credentials/{username}` | Core | No | 204 | No | No |

Password is session-memory only in the SPA. Exchange always hits Planets.nu. Probe does not.

### 1.2 Shell bootstrap

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/shell/bootstrap` | BFF | Yes | `{showInitialGame, computeDiagnosticsEnabled}` | No | No |

No Core counterpart. Config + whether the diagnostics modal shows compute controls.

### 1.3 Game list and GameInfo

`GameInfo` is `game` + `players` + `relations` + `settings` + schedule/win fields ([`packages/api/api/models/game.py`](../../packages/api/api/models/game.py)). The header uses it for latest turn, player names, finished vs running, and settings that gate Stellar Cartography layers.

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/games` | BFF | Yes | `{games: [{id, sectorName?}]}` from storage | No | No |
| `GET /bff/games/{game_id}/info` | BFF | Yes | Stored `GameInfo` (no Planets.nu) | No | No |
| `POST /bff/games/{game_id}/info` | BFF | Yes (select/add game) | Refreshed `GameInfo` (`operation: refresh` + username/password) | No -- **loadinfo**, not loadturn | No |
| `GET /api/v1/games/{game_id}/info` | Core | No | Stored `GameInfo` | No | No |
| `POST /api/v1/games/{game_id}/info` | Core | No | Same refresh | No -- loadinfo | No |

There is **no** Core `GET /api/v1/games` list. Listing stored games is BFF-only (Core `GameService.list_stored_games()` in-process).

### 1.4 TurnInfo and turn-ensure

`TurnInfo` is the full turn snapshot: settings, viewpoint `player`, `players`, `scores`, `planets`, `ships`, `starbases`, ion storms, nebulae, stars, minefields, relations, messages, notes, VCRs, races, hulls/beams/engines/torps, blackholes, artifacts, wormholes, etc.

The SPA **does not render raw `TurnInfo`**. After ensure it only extracts per-player usernames and relation edges. Everything the human *sees* as game state goes through analytics or GameInfo.

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `POST /bff/games/{game_id}/turns/ensure` | BFF | Yes (required before analytics) | Full `TurnInfo`. Body: `{turn, perspective, username, password?}`. Username may be empty when the turn is already stored. | **Yes** -- `get_turn_info` first; Planets.nu `loadturn` only on miss | No |
| `POST /api/v1/games/{game_id}/{perspective}/turns/{turn_number}/ensure` | Core | No | `TurnInfo`. Credentials in body (`RefreshGameInfoParams`), ids in path. | **Yes** | No |
| `GET /api/v1/games/{game_id}/{perspective}/turns/{turn_number}` | Core | No | Stored `TurnInfo` or 404 | **No** -- will not fetch | No |

BFF has **no GET turn**. The human path is always POST ensure. Core GET is the stored-read counterpart an agent would need for "is this turn already local?" without triggering upstream.

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/games/{game_id}/turns/{turn_number}/stored-perspectives` | BFF | Yes (viewpoint dropdown) | `{perspectives: number[]}` slots that already have turn data | No | No |

No dedicated Core HTTP for stored-perspectives (Core `TurnLoadService` in-process).

### 1.5 Load-all turns

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/games/{game_id}/turns/load-all-status?username=` | BFF | Yes | `{game_id, complete, is_game_finished, expected_perspectives, latest_turn}` | No (status only) | No |
| `POST /bff/games/{game_id}/turns/load-all/stream` | BFF | Yes | NDJSON: `progress` / `complete` / `error`. Complete result: turns written/skipped, perspectives, final-turn failures. | **Yes** -- bulk loadturn / archive import | No |
| `GET /api/v1/games/{game_id}/turns/load-all-status` | Core | No | Same status | No | No |
| `POST /api/v1/games/{game_id}/turns/load-all/stream` | Core | No | Same NDJSON | **Yes** | No |

---

## 2. Analytics catalog, table, and map

Shared catalog: `TURN_ANALYTIC_CATALOG` in [`packages/api/api/analytics/catalog.py`](../../packages/api/api/analytics/catalog.py). BFF `GET /bff/analytics` returns that metadata. Core has no catalog HTTP; `GET /api/v1/games/.../analytics/{analytic_id}` is the compute/dispatch endpoint (map-oriented wire; BFF splits table vs map).

| id | Display name | Type | Table | Map | Orchestrator? |
|----|--------------|------|-------|-----|----------------|
| `base-map` | Map | base (always fetched in map mode; not in sidebar) | No | Yes -- planet nodes + `normalWellCells` | No -- sync from `TurnInfo` |
| `scores` | Scores | selectable | Yes | No | Table GET: **no** (`route_table_map=False`). Inference stream: **yes** |
| `connections` | Connections | selectable | No | Yes -- `routes` (empty nodes/edges) | No -- sync |
| `stellar-cartography` | Stellar Cartography | selectable | No | Yes -- overlay circles, wormhole geometry | No -- sync |
| `fleet` | Fleet | selectable | Yes (stream in SPA) | Yes (overlays from stream) | **Yes** (`route_table_map=True`) |
| `visibility` | Visibility | selectable | No | Yes -- `regionOverlays` | No -- sync |
| `homeworld-locator` | Homeworld locator | selectable | Catalog `supportsTable=false`; SPA still GETs `/table` for the map-mode panel | Yes -- markers/rows/regionOverlays | **Yes** |

Generic BFF reads (every selectable analytic plus base-map):

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/analytics` | BFF | Yes | `{analytics: [{id, name, supportsTable, supportsMap, type}]}` | No | No |
| `GET /bff/analytics/{analytic_id}/table?gameId&turn&perspective&username?` | BFF | Yes for `scores`; fleet tile uses stream instead; homeworld panel uses table GET in map mode | Analytic-specific JSON (see below) | **Requires stored turn** (`get_turn_info`). Homeworld may **auto-ensure other turns** if `username` is set (baseline turn 1). | Fleet + homeworld: orchestrator ensure then shape. Scores: **sync** scoreboard projection. |
| `GET /bff/analytics/{analytic_id}/map?gameId&turn&perspective&...` | BFF | Yes for all map analytics | Analytic-specific map JSON | Same as table (stored turn; homeworld username auto-ensure) | Fleet + homeworld: orchestrator. Others: sync. |
| `GET /api/v1/games/{game_id}/{perspective}/turns/{turn_number}/analytics/{analytic_id}` | Core | No | Same Core dict BFF reshapes | Same | Same `TurnAnalyticService.get_turn_analytics` |

Connections map extra query params (BFF aliases): `warpSpeed` (1-9), `gravitonicMovement`, `flareMode` (`off`/`include`/`only`), `flareDepth` (1-3), `includeIllustrativeRoutes`. Scores table extra: `includeBuildInference` (adds stub inference column; live results come from the stream).

Optional `username` on table/map: not a second login. It is the turn-load credential so homeworld compute can `ensure_turn` missing historical turns via the stored account API key.

### 2.1 Per-analytic table/map payloads

| Analytic | Table wire | Map wire |
|----------|------------|----------|
| `base-map` | N/A | `{analyticId, nodes[], edges: []}`. Each node: id `p{planetId}`, x/y, public planet JSON, `ownerName`, `normalWellCells` (warp-well overlay; **not** a separate HTTP call in the SPA). |
| `scores` | `{analyticId, columns, rows, rowPlayerIds, includeBuildInference?, inferenceByRow?}`. Columns: Race (player), Planets, Starbases, War Ships, Freighters, Military, Priority Points, optional Build inference. | N/A |
| `connections` | N/A | `{analyticId, nodes: [], edges: [], routes}` -- planet-pair reachability; SPA draws edges on base-map nodes. |
| `stellar-cartography` | N/A | Overlay circles (debris, nebulae, ion, clusters, black holes) + wormhole graph geometry. |
| `fleet` | GET table: `{analyticId, defaultActiveOnly, players[], componentCatalog?}`. SPA **does not** use GET table for the live tile. | GET map: `{analyticId, players: [{playerId, nodes: [], overlayCircles: []}]}` -- placeholders. Live map rings/trails come from the **table stream**. |
| `visibility` | N/A | `{analyticId, regionOverlays, nodes: [], edges: []}` -- ship-scan and Sensor Sweep coverage. |
| `homeworld-locator` | Same payload as map (passthrough). | `{analyticId, available, inactiveReason?, baselineDegraded, baselineTurn?, markers?, rows?, regionOverlays?, nodes: [], edges: []}`. |

---

## 3. Per-analytic streams and controls

These are first-class human surfaces: the Scores tile, Fleet tile, and Homeworld map panel are incomplete without them.

### 3.1 Scores inference

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/analytics/scores/inference?gameId&turn&perspective&playerId` | BFF | Client exists; **tile uses table-stream**, not this GET | One row: `displayStatus`, `status`, `summary`, `solutionCount`, `isComplete`, `solutions[]`, diagnostics, optional fleet-torp overlay fields | Stored turn | Orchestrator inference for that player |
| `GET /bff/analytics/scores/inference/table-stream?playerIds=` | BFF | **Yes** (primary) | NDJSON: `solution`, `progress`, `complete`, `error`, `globalPause` | Stored turn | **Yes** -- scores `materialize` + `tier_solve` |
| `GET /bff/analytics/scores/inference/hull-catalog?playerId=` | BFF | Yes (inference detail) | Master hull catalog + user/effective masks | Stored turn | No (catalog/mask read) |
| `PUT /bff/analytics/scores/inference/hull-catalog` | BFF | Yes | Same mask after persist | No | Invalidates / reschedules inference |
| `DELETE /bff/analytics/scores/inference/hull-catalog` | BFF | Yes | Mask reset to game-type defaults | No | Invalidates / reschedules |
| `GET /bff/analytics/scores/inference/global-pause` | BFF | Yes | `{paused, heldJobCount, ...}` | No | No (control plane) |
| `POST /bff/analytics/scores/inference/global-pause` | BFF | Yes | Pause all scoreboard inference for the turn scope | No | Holds orchestrator work |
| `DELETE /bff/analytics/scores/inference/global-pause` | BFF | Yes | Resume | No | Wakes work |
| `POST /bff/analytics/scores/inference/recompute` | BFF | Yes | Clears host-turn inference persistence and reschedules rows | No | **Yes** -- wipe + reschedule |

Core twins live under `/api/v1/games/{game_id}/{perspective}/turns/{turn_number}/analytics/scores/inference/...` (same verbs). SPA never calls them.

### 3.2 Fleet stream and catalog

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/analytics/fleet/table-stream?playerIds=` | BFF | **Yes** (table tile and map overlays) | NDJSON: `ledger_updated`, `record_refined`, `provenance`, `complete`, `error` | Stored turn | **Yes** -- observation + finalization legs |
| `GET /bff/analytics/fleet/component-catalog` | BFF | Yes (names without waiting on fleet compute) | `{analyticId, componentCatalog: {hulls, engines, beams, torpedoes}}` from `TurnInfo` | Stored turn (`get_turn_info`) | **No** |
| `GET /api/v1/games/.../analytics/fleet/table-stream` | Core | No | Same NDJSON | Stored turn | **Yes** |

No Core HTTP for component-catalog (BFF reads `TurnInfo` in-process).

### 3.3 Homeworld locator mutations

Catalog marks homeworld **map-only**, but the map-mode accordion calls **GET table** for the same candidate payload.

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `POST /bff/analytics/homeworld-locator/assertions` | BFF | Yes (map context menu / panel) | Same locator payload after upsert/revoke. Body: `{axis: location\|ownership, action: upsert\|revoke, planetId?, sectorIndex?, ownerSlot?}` | Stored turn | Recompute/view after assertion |
| `POST /bff/analytics/homeworld-locator/refresh` | BFF | Yes | Same payload after wipe of machine state (asserts kept) | **Yes** -- rebuild via ensure (historical turns) | **Yes** |
| Core `POST .../analytics/homeworld-locator/assertions` | Core | No | Same | Same | Same |
| Core `POST .../analytics/homeworld-locator/refresh` | Core | No | Same | Same | Same |

---

## 4. Query-shaped concept endpoints

These answer a **point question** instead of dumping `TurnInfo`. They are the HTTP cousins of `api/concepts/` (warp wells, stellar cartography, flare points). Overlap with gameplay research: [`docs/research/gameplay-advisor-queries.md`](gameplay-advisor-queries.md).

### 4.1 Used by the SPA

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/games/{game_id}/{perspective}/turns/{turn_number}/concepts/stellar-cartography/sample?x&y` | BFF | Yes (map hover tooltip) | `{x, y, entries: [{layer, lines[]}]}` stacked SC layers at a cell | Stored turn | No -- concept sample |
| `GET /bff/games/{game_id}/{perspective}/turns/{turn_number}/concepts/stellar-cartography/summary` | BFF | Yes | `{ionStormCount, nuIonStorms}` | Stored turn | No |
| Core `GET .../concepts/stellar-cartography/sample` | Core | No | Same | Stored turn | No |
| Core `GET .../concepts/stellar-cartography/summary` | Core | No | `{ion_storm_count, nu_ion_storms}` (snake_case on Core; BFF camelCase on summary) | Stored turn | No |

### 4.2 Exposed on BFF, not called by the SPA

Warp-well **drawing** uses `normalWellCells` on **base-map nodes**. These routes exist as explicit queries:

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `POST /bff/games/.../concepts/warp-wells/coordinate-in-well` | BFF | No (OpenAPI only) | `{inside: bool}`. Body: `{planet_id, map_x, map_y, well_type: normal\|hyperjump}` | Stored turn | No |
| `GET /bff/games/.../concepts/warp-wells/cells?planet_id&well_type` | BFF | No | `{cells: [{x, y}]}` | Stored turn | No |
| Core POST/GET twins under `/api/v1/games/.../concepts/warp-wells/...` | Core | No | Same | Stored turn | No |

Hyperjump wells are defined in Core and these APIs; the map **does not draw** them ([user guide](../user-guide.md)).

### 4.3 Core-only (no BFF, no SPA)

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /api/v1/concepts/flare-points?warp_speed&movement_type` | Core | No | `{flare_points: [{waypoint_offset, arrival_offset, direct_aim_arrival_offset}]}` for `regular` or `gravitonic` | **None** -- static catalog, no game/turn | No |

The Connections analytic **embeds** flare geometry in `routes`. The SPA never lists raw flare offsets.

---

## 5. Operator / diagnostics (human-visible, not analysis)

The header **Diagnostics** modal is a Console UI. It is operator telemetry, not game advice. Listed for completeness so later parity tickets can include or exclude it.

| Route | Layer | SPA | Returns | Turn ensure | Compute |
|-------|-------|-----|---------|-------------|---------|
| `GET /bff/diagnostics/recent` | BFF | Yes | MRU request timing trees (`includeDiagnostics=true` on other BFF calls) | No | No |
| `GET /diagnostics/recent` | Root alias | Fallback if `/bff` 404s | Same | No | No |
| `GET /bff/diagnostics/homeworld/layout-prior-reports` | BFF | Yes (Homeworlds tab) | Solver run reports for the shell | No | No (reads reports) |
| `GET /bff/diagnostics/compute/enabled` | BFF | Indirect via bootstrap | `{enabled}` | No | No |
| `GET /bff/diagnostics/compute/snapshot` | BFF | Yes when compute diag on | Orchestrator snapshot | No | Snapshot only |
| `GET /bff/diagnostics/compute/freeze-status` | BFF | Yes | Freeze armed + allowlist | No | No |
| `PUT /bff/diagnostics/compute/freeze` | BFF | Yes | Snapshot after arm/disarm | No | Holds dispatch |
| `PUT /bff/diagnostics/compute/allowlist` | BFF | Yes | Snapshot | No | Restricts which players run |
| `POST /bff/diagnostics/compute/single-step` | BFF | Yes | Snapshot after one in-focus step | No | Releases **one** orchestrator step |

No Core HTTP twins; diagnostics services are called from BFF.

---

## 6. Dual-path cheat sheet (BFF vs Core)

| Capability | BFF (SPA) | Core HTTP |
|------------|-----------|-----------|
| List stored games | `GET /bff/games` | None |
| Shell bootstrap | `GET /bff/shell/bootstrap` | None |
| GameInfo stored / refresh | `GET/POST /bff/games/{id}/info` | `GET/POST /api/v1/games/{id}/info` |
| Stored perspectives | `GET /bff/games/{id}/turns/{t}/stored-perspectives` | None |
| Ensure turn | `POST /bff/games/{id}/turns/ensure` (ids in **body**) | `POST /api/v1/games/{id}/{p}/turns/{t}/ensure` (ids in **path**) |
| Get stored TurnInfo without ensure | None | `GET /api/v1/games/{id}/{p}/turns/{t}` |
| Load-all | `GET .../load-all-status`, `POST .../load-all/stream` | Same under `/api/v1/games/{id}/turns/` |
| Credentials | `/bff/credentials/...` | `/api/v1/credentials/...` |
| Analytics catalog | `GET /bff/analytics` | None |
| Analytic table / map | `GET /bff/analytics/{id}/table\|map` (scope in **query**) | `GET /api/v1/games/{id}/{p}/turns/{t}/analytics/{id}` (scope in **path**) |
| Scores / fleet / homeworld extras | `/bff/analytics/scores\|fleet\|homeworld-locator/...` | `/api/v1/games/.../analytics/scores\|fleet\|homeworld-locator/...` |
| SC sample / summary | BFF games-concepts paths | Same path under `/api/v1/games` |
| Warp-well point/cells | BFF games-concepts paths | Same under `/api/v1/games` |
| Flare-point catalog | None | `GET /api/v1/concepts/flare-points` |
| Diagnostics | `/bff/diagnostics/...` | None |
| Store CRUD | None | `/api/v1/store/{path}` |

---

## 7. Facts later tickets depend on

These are observations, not catalog-shape or parity decisions:

1. **Human parity is BFF-shaped.** The SPA never calls `/api`. Matching the human app means matching `/bff/...` (and the few root aliases), not the Core path layout.
2. **Raw `TurnInfo` is not a human surface.** Ensure returns it; the UI throws most of it away. Analytics and concept queries are what the human actually sees.
3. **Three analytics hit the orchestrator** on the human path: **fleet** (stream + table/map GET), **homeworld-locator** (map/table GET, refresh), **scores inference** (stream, not the scoreboard table GET).
4. **Sync analytics** (base-map, connections, stellar-cartography, visibility, scores table) need a stored turn and then run in-request from `TurnInfo` / concepts -- no orchestrator wait.
5. **Query-shaped HTTP already exists** for warp-well point/cells, SC sample/summary, and flare-point tables. Only SC sample/summary are wired in the SPA; warp-well HTTP is redundant with base-map cells; flare-points have no BFF.
6. **Writes that are not Planets.nu orders** (still human-visible): credential exchange/drop, hull-catalog mask, inference pause/recompute, homeworld assertions/refresh, compute-diagnostics freeze. Map destination still excludes **submitting orders**.
7. **Streaming** is how the human sees long-running fleet and scores work (NDJSON), not a single JSON GET.

---

## References

- [`docs/user-guide.md`](../user-guide.md) -- human UI
- [`docs/research/gameplay-advisor-queries.md`](gameplay-advisor-queries.md) -- query families vs `api/concepts/`
- [`docs/design-analytics-structure.md`](../design-analytics-structure.md) -- catalog vs BFF descriptors
- [`docs/design-compute-orchestrator.md`](../design-compute-orchestrator.md) -- table/map batch vs streams
- [`docs/adr/0011-fleet-stream-behind-table-and-map.md`](../adr/0011-fleet-stream-behind-table-and-map.md) -- fleet stream as the live surface
- Frontend clients: [`packages/frontend/src/api/bff.ts`](../../packages/frontend/src/api/bff.ts), `credentialsClient.ts`, `bffComputeDiagnostics.ts`, `bffLayoutPriorDiagnostics.ts`, `analytics/homeworld-locator/api.ts`
- BFF routers: [`packages/bff/bff/app.py`](../../packages/bff/bff/app.py)
- Core routers: [`packages/api/api/app.py`](../../packages/api/api/app.py)
