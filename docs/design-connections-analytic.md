# Design: Connections map analytic

This document describes the **Connections** analytic: **one-turn ship reachability** between planets using **warp wells** and optional **flare** geometry, from Core logic through the BFF to the combined React Flow map.

**Code (primary):**

| Layer | Location |
|--------|----------|
| Reachability + flare pairing | `packages/api/api/concepts/planet_connections.py` |
| Flare offset tables (per warp, regular vs gravitonic) | `packages/api/api/concepts/flare_points.py`, `flare_point_quadrant_seeds.py` |
| Warp well geometry (shared with other features) | `packages/api/api/concepts/warp_well.py` |
| Core service entry | `packages/api/api/services/game_service.py` -- `get_turn_analytics(..., analytic_id="connections", ...)` |
| BFF map route | `packages/bff/bff/routers/analytics.py` -- `GET .../analytics/connections/map` |
| SPA: fetch, merge with base map, styling | `packages/frontend/src/api/bff.ts`, `MainArea.tsx`, `MapGraph.tsx` |
| SPA: enable + parameters | `packages/frontend/src/App.tsx` (`connectionsMapParams`), `AnalyticsBar.tsx` |
| Tests | `packages/api/tests/test_planet_connections.py`, `packages/bff/tests/test_analytics.py` |

Related: [Warp wells on the map](design-warp-wells-map.md) (well drawing and concept HTTP), [vga-planets-domain-context.md](vga-planets-domain-context.md) (domain), [Frontend and backend state](design-frontend-and-backend-state.md) (query keys and gating).

---

## 1. Purpose

For a loaded **turn** and **perspective**, Connections answers: **which planet pairs can reach each other in one movement** at a chosen **warp** (1--9), with optional **gravitonic** doubled range, and how **flare-assisted** routes relate to **direct** warp-well reachability.

Output is a list of **routes** (unordered pairs with flags), not a full pathfinder over multiple turns.

---

## 2. Domain model (simplified Host alignment)

- **Max travel distance** in map units: `warp_speed ** 2`, or **twice** that when **gravitonic movement** is on (`max_travel_distance` in `planet_connections.py`).
- **Normal warp well** around each planet (non--debris-disk): Euclidean distance from planet map cell to query point **≤ 3** (`NORMAL_RADIUS` in `warp_well.py`). Debris-disk planets use a **point-only** well for distance checks (see `planet_connections` helpers).
- **Direct connection:** From planet A, the **minimum distance** from A’s position to planet B’s **well** (or point, for debris) is **≤ max travel**. Undirected edge if either direction qualifies.
- **Flare connection:** Uses a **static table** of **flare points** per warp and movement kind. Each row gives:
  - **`waypoint_offset`** -- where the ship is **ordered** (relative to start),
  - **`arrival_offset`** -- where the ship **ends** after the Host movement formula,
  - **`direct_aim_arrival_offset`** -- where a straight aim at the arrival cell would end (used in data; reachability uses **arrival** vs wells).

  A pair is **flare-reachable** from A toward B if **some** table row places **`arrival_offset`** from A inside B’s **simplified normal well**. **Do not** require Euclidean distance from A to the **waypoint** to be ≤ max travel: Host allows waypoints **beyond** `warp²`; the table rows are authoritative for valid flare geometry at that warp.

- **Exclusive flare** (for labeling): flare-reachable **and** **not** directly connected. Modes (below) decide whether exclusive-flare pairs, direct pairs, or both appear in the API output.

---

## 3. `FlareConnectionMode` (Core enum, BFF query `flareMode`)

| Value | Meaning |
|--------|---------|
| `off` | Return only **direct** pairs; `viaFlare` is always false on returned routes. Pairs that are **only** flare-reachable are **omitted**. |
| `include` | Return **direct** pairs (`viaFlare: false`) **and** **exclusive** flare pairs (`viaFlare: true`). |
| `only` | Return **only** exclusive flare pairs (`viaFlare: true`). |

Strings on the wire match the enum values: `off`, `include`, `only`.

---

## 4. Core API

- There is **no** separate Connections-only public route required for the SPA; the BFF calls **`GameService.get_turn_analytics`** with `analytic_id == "connections"`.
- The general Core pattern is `GET /api/v1/games/{game_id}/{perspective}/turns/{turn_number}/analytics/{analytic_id}` (see [design-issue-10-base-map-from-core.md](design-issue-10-base-map-from-core.md)); **`connections`** uses the same analytics hook with keyword args:
  - `connection_warp_speed` (int 1--9),
  - `connection_gravitonic_movement` (bool),
  - `connection_flare_mode` (`FlareConnectionMode`),
  - `connection_flare_depth` (int 1--3, default **1**): **hop budget** for mixed normal-move + flare BFS. Each hop is a normal well move (within max travel) or a flare from the static table; a valid path must use **at least one** flare. This is not a "flares in a row" count. Pair discovery also unions **per-k** center-distance **annuli** (k = 1…depth), so increasing depth can only add candidate pairs and longer mixed paths, not remove pairs that were already eligible at a smaller depth.
  - Optional: `connection_include_illustrative_routes` when the client wants per-hop `illustrativeRoute` steps on flare rows (BFF may set this from the SPA when depth ≥2 and flares are on).

Implementation loads **`TurnInfo`**, takes `list(turn.planets)`, and calls **`connection_routes_for_planets`** (`planet_connections` package).

---

## 5. BFF

**List entry:** `ANALYTICS_LIST` in `packages/bff/bff/routers/analytics.py` includes `id: "connections"`, map-capable, selectable.

**Map:**

- **Method / path (mounted at `/bff`):** `GET /bff/analytics/connections/map`
- **Required query:** `gameId`, `turn`, `perspective` (same as other turn-scoped analytics).
- **Connections-specific query (defaults in parentheses):**
  - `warpSpeed` (int 1--9, default **9**),
  - `gravitonicMovement` (bool, default **false**),
  - `flareMode` (`off` \| `include` \| `only`, default **off** for raw HTTP callers without the query; the SPA sends an explicit value),
  - `flareDepth` (int 1--3, default **1**): same semantics as Core `connection_flare_depth` (mixed-hop budget + annulus layers; at least one flare in the path),
  - `includeIllustrativeRoutes` (bool, default **false**): forwarded to Core; the SPA sets **true** when `flareMode` is not `off` and `flareDepth` ≥ 2 so multi-hop paths can return intermediate waypoints.

**Response shape** (map payload):

- `analyticId`: `"connections"`
- `nodes`: `[]`
- `edges`: `[]`
- `routes`: array of `{ "fromPlanetId": int, "toPlanetId": int, "viaFlare": bool }` with **canonical ordering** `fromPlanetId < toPlanetId`.

The BFF does not recompute logic; it forwards to Core **`get_turn_analytics`** with the connection kwargs.

---

## 6. Frontend

### 6.1 Enabling and parameters

- **Connections** appears in the **Analytics** sidebar as a **checkbox** (map mode). It must be **enabled** for the map request to run (together with the always-included **base map** layer when map mode is active).
- **`connectionsMapParams`** in `App.tsx` holds:
  - **`warpSpeed`** (1--9),
  - **`gravitonicMovement`**,
  - **`flareMode`** (`off` \| `include` \| `only`),
  - **`flareDepth`** (1--3; hop budget / annulus cap as above; **Depth** in the UI).

Controls live in **`AnalyticsBar`** (Connections tile): **Flares** and **Depth** are shown when Connections is enabled; **Warp** and **Gravitonic** sit in the expandable section (chevron).

**Important:** With **`flareMode: off`**, the server **drops** pairs that are **only** reachable via flare. For maps where the only link between two planets is a flare, you must use **`include`** or **`only`** to see an edge.

### 6.2 Fetch and cache key

`MainArea` uses **`useQueries`**. For **connections**, the TanStack **query key** includes (in order): `'analytic'`, `'connections'`, `'map'`, `gameId`, `turn`, `perspective`, **`warpSpeed`**, **`gravitonicMovement`**, **`flareMode`**, **`flareDepth`**. Changing any of these refetches the connections overlay.

`fetchAnalyticMap` passes the three connection parameters as query string fields on the GET (see `analyticMapQueryString` in `bff.ts`).

### 6.3 Merging into the shared map

**`combineMapData`** (`MainArea.tsx`):

- Base map nodes use ids like **`base-map:p{planetId}`** (from planet nodes returned by the base-map analytic).
- Each **route** becomes an **edge** from **`base-map:p{fromPlanetId}`** to **`base-map:p{toPlanetId}`**.
- For **`flareMode === 'only'`**, client-side filtering keeps only routes with **`viaFlare === true`** before drawing (defensive if a stale cached response had mixed rows). **`off`** filters out flare-only routes the same way when merging. **`include`** draws all returned routes.

### 6.4 Edge styling

**`MapGraph.tsx`:** edges with **`viaFlare`** use a **dashed** stroke and **yellow** tint; direct connections use solid gray.

---

## 7. Performance note

`connection_routes_for_planets` uses a **uniform grid spatial index** over planet positions to limit candidate pairs; it still scales with planet count and scan radius derived from max travel, flare extent, and well radius. Very large turns (hundreds of planets) are supported but heavier than tiny fixtures.

---

## 8. Tests to update when behavior changes

- **`packages/api/tests/test_planet_connections.py`** -- routing modes, spatial index, flare vs direct (e.g. waypoint farther than `warp²`).
- **`packages/bff/tests/test_analytics.py`** -- BFF map response shape and query forwarding for `connections`.

Regenerate the SPA OpenAPI types (`packages/frontend/src/api/schema.ts`) if BFF query or response models change (`openapi-typescript` against `/bff/openapi.json`).

---

## 9. Changelog notes

When changing reachability rules, flare tables, or HTTP fields, update this doc, the [user guide](user-guide.md) (Connections / map sections), and any golden tests. When changing **well geometry** shared with other features, update [design-warp-wells-map.md](design-warp-wells-map.md) and `warp_well.py` first.
