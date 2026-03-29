# Design: Issue #10 - Base map from Core turn data

**Source:** [GitHub Issue #10 - [Feature]](https://github.com/SteveDraper/Planets-Console/issues/10)

This document describes a design for Issue #10. **Implementation is out of scope** for this doc; it is a design and acceptance reference only.

---

## 1. Goal

Hook the “base map” pseudo-analytic (the always-on `type: "base"` map layer) to the Core REST API layer so map data comes from stored game/turn state (storage) instead of dummy data currently returned by the BFF.

---

## 2. Current state

### 2.1 Frontend map assembly

Map mode fetches multiple analytics in a combined way:
- fetch the **base map** first
- then fetch any **enabled selectable map analytics**
- combine nodes/edges with id-prefixing so layers merge into a single React Flow graph

Key code paths:
- `packages/frontend/src/components/MainArea.tsx`
  - `baseMapId(...)` finds the analytic with `type === 'base' && supportsMap`
  - `mapIdsToFetch(...)` fetches base first, then overlays

### 2.2 BFF “base map” implementation

The base map is currently hard-coded in the BFF:
- `packages/bff/bff/routers/analytics.py`
  - returns a placeholder square (nodes + edges) when `analytic_id == "base-map"`

### 2.3 Core already has game/turn + planet data

Core already provides turn data from storage:
- `GET /api/v1/games/{game_id}/{perspective}/turns/{turn_number}` in `packages/api/api/routers/games.py`
- `packages/api/api/services/game_service.py` loads:
  - `games/{game_id}/{perspective}/turns/{turn_number}`

The domain `Planet` model includes `id`, `x`, and `y`:
- `packages/api/api/models/planet.py`

---

## 3. Scope

### In scope
- Replace dummy data for `base-map` with real planet nodes from the displayed game turn.
- Base-map edges must be empty for now.
- Introduce/shape any necessary Core endpoint(s) and BFF integration, keeping layering rules:
  - frontend calls only BFF
  - BFF reshapes/aggregates; no business logic
  - Core owns business logic; storage access stays inside `packages/api/storage/`
- Add/plan unit tests for new behavior at the Core and BFF layers.

### Out of scope (for this issue)
- Implementing the “real” game+turn context wiring end-to-end from the UI (login, selected game, selected turn, etc.).
- Non-base map overlays (selectable analytics) beyond ensuring base-map is still composed correctly.
- Adding edges into the base map.

---

## 4. Proposed design

### 4.1 Required data flow (layered)

```mermaid
flowchart TD
  Frontend[Frontend Map View] -->|GET /bff/analytics/base-map/map| BFF[BFF analytics router]
  BFF -->|GET Core game+turn| Core[Core REST API]
  Core -->|Storage get(games/{gameId}/{perspective}/turns/{turnNumber})| Storage[StorageBackend]
  Storage --> Core
  Core -->|Planet nodes only| BFF
  BFF -->|nodes, edges:[]| Frontend
```

### 4.2 Core API endpoint(s)

Issue #10 requires that base-map data be derived from the displayed `gameId` and `turnNumber`.

Because Core already returns the whole `TurnInfo`, the final design uses the more general per-analytic pattern so the BFF can treat `base-map` like any other analytic.

Final Core route naming:
- `GET /api/v1/games/{game_id}/{perspective}/turns/{turn_number}/analytics/{analytic_id}`
  - `analytic_id == "base-map"` returns planet nodes derived from the turn
  - edges are an empty array for now

Response contract (Core -> BFF -> frontend payload):
- `analyticId`: `base-map`
- `nodes`: planet nodes with:
  - `id` as `p{id}`
  - `x`, `y` from `Planet.x` and `Planet.y`
  - `label` optional (frontend supports it today)
- `edges`: `[]`

### 4.3 Error behavior / missing context

Issue #10 says:
- `game id` and `turn number` can be `None`
- however, it also says to initialize to test values: `628580` and `111`

Because this issue is explicitly about replacing dummy data, the design chooses a pragmatic behavior:
- The BFF uses hard-coded test `gameId` and `turnNumber` (`628580` / `111`) until the UI context wiring ticket lands.
- The Core endpoint treats the parameters as required for now (type `int` in FastAPI), so missing context is a frontend/BFF responsibility rather than a core semantic.

Resulting behavior:
- If the storage key `games/{gameId}/{perspective}/turns/{turnNumber}` is missing, Core returns `404` via existing store error mapping.

This keeps the design consistent with existing Core routers and services:
- routers parse path parameters into `int`
- services call storage `get(...)`

---

## 5. BFF integration

### 5.1 Keep the frontend contract stable

Frontend expects the existing BFF endpoint shape:
- `GET /bff/analytics/{analytic_id}/map`
- for base-map, it expects:
  - `analyticId`
  - `nodes` (with `id`, `label`, `x`, `y`)
  - `edges` (currently used by React Flow; must be empty for base-map)

So BFF should preserve:
- analytic id: `base-map`
- edges: `[]`

### 5.2 Replace dummy logic in `packages/bff/bff/routers/analytics.py`

Current behavior:
- special-cases `analytic_id == "base-map"` and returns dummy square nodes and edges.

Final behavior:
- for `analytic_id == "base-map"`, obtain the base map from Core-layer service logic (and ensure sample data exists in ephemeral storage):
  - seed/sample: make sure turn data exists for the hard-coded base-map context
  - call `GameService.get_turn_analytics(game_id, perspective, turn_number, "base-map")`
- then return a `MapDataResponse`-compatible payload to the frontend:
  - `analyticId: "base-map"`
  - `nodes` populated from turn planets (`p{id}`, `x`, `y`)
  - `edges: []`

### 5.3 Game+turn test values “initialization”

Since the UI does not yet wire game+turn state, BFF will use Issue #10 test initialization values:
- `game_id = 628580`
- `turn_number = 111`

Implementation choice:
- Hard-code these values in the BFF base-map route for now (as the issue requests).
- A follow-up ticket can replace this with real context wiring.

---

## 6. Tests plan (to implement)

### 6.1 Core tests
- Test that the new Core endpoint returns planet nodes:
  - uses the `TurnInfo` stored at `games/628580/1/turns/111`
  - validates the `id` format is `p{id}`
  - validates `x` and `y` match the underlying planet record
  - validates edges are empty

### 6.2 BFF tests
- Update/extend existing BFF analytics tests:
  - `packages/bff/tests/test_analytics.py`
  - Ensure `GET /analytics/base-map/map` returns:
    - `analyticId == "base-map"`
    - nodes populated from Core (mock Core or use integration-style tests depending on existing patterns)
    - edges empty

---

## 7. Acceptance criteria

- Map mode base layer is no longer dummy data.
- Base-map layer contains planet nodes derived from stored turn data.
- Base-map layer edges are empty.
- BFF endpoint contract consumed by the frontend remains compatible.
- Core and BFF include unit tests for the new behavior.

---

## 8. Open questions

1. Transport model choice: should the Core endpoint return a “map-like” `{nodes, edges}` payload or a Core-only `{planets}` payload that BFF transforms? This doc chooses `{nodes, edges}` for simplicity and contract stability.
2. Label field: does the frontend require `label`? (frontend supports it but map rendering currently mainly needs `x/y` and `id`; this should be confirmed once base-map rendering is fully implemented beyond placeholder.)

---

## 9. Related: Connections overlay

**Travel edges** between planets are **not** part of the base-map payload. They come from the selectable **Connections** analytic (`GET /bff/analytics/connections/map`), merged in the SPA onto **`base-map:p{planetId}`** nodes. See [design-connections-analytic.md](design-connections-analytic.md).

