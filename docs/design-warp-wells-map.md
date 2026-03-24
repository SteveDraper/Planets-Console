# Warp wells on the map

This document describes how the console models **warp wells** in code: **Core API** (`api.concepts`), **HTTP** (turn-scoped routes), **BFF** (shallow `GameService` calls), and the **React Flow** map (grid overlays, zoom thresholds).

**Code (primary):**

| Area | Location |
|------|----------|
| Canonical well rules (Python) | `packages/api/api/concepts/warp_well.py` |
| Turn lookup + service API | `packages/api/api/services/game_service.py` (`get_planet_from_turn`, `warp_well_*`) |
| Core REST routes | `packages/api/api/routers/game_concepts.py` |
| HTTP request/response shapes | `packages/api/api/transport/concept_warp_well.py` |
| BFF mirror routes | `packages/bff/bff/routers/games.py` |
| Frontend (map UI only) | `packages/frontend/src/lib/warpWell.ts`, `MapGraph.tsx` |
| Planet `debrisdisk` on map nodes | Turn snapshot on `MapNode.planet` (see `packages/frontend/src/api/bff.ts` normalization) |

Related domain context: [vga-planets-domain-context.md](vga-planets-domain-context.md) (tactics / routing). This doc is about **console behavior**, not host rules.

---

## 1. Warp well types (logic)

Two logical kinds, used by **`isCoordinateInWarpWell`**:

| Type | Rule (Cartesian / Euclidean in map coordinates) |
|------|--------------------------------------------------|
| **normal** | Distance from planet map cell index `(planetX, planetY)` to query `(queryX, queryY)` is **≤ 3** |
| **hyperjump** | Same distance is **strictly &lt; 3** |

Distance is **`Math.hypot(Δx, Δy)`** on the map plane. The planet and query coordinates are whatever the caller passes (typically integer cell indices from map data).

**Debris disk:** If the planet snapshot has non-zero **`debrisdisk`** (or camelCase **`debrisDisk`**), the planet has **no** warp wells: **`planetIsInDebrisDisk`** is true and **`isCoordinateInWarpWell`** always returns false.

Exported helpers:

- **`planetIsInDebrisDisk(planet)`**
- **`warpWellCartesianDistance`**
- **`isCoordinateInWarpWell(planetX, planetY, planet, queryX, queryY, wellType)`**
- **`mapCellsWithCenterInNormalWarpWell(planetMapX, planetMapY)`** -- map cells `(gx, gy)` whose center is in the normal well: `hypot(gx - px, gy - py) ≤ 3` (equivalent to Euclidean distance between cell centers `(gx+0.5, gy+0.5)` and `(px+0.5, py+0.5)`).

---

## 2. Map visualization (normal well only)

Only the **normal** well is drawn today. The overlay:

1. Collects every map cell whose **center** lies in the normal well (same rule as **`mapCellsWithCenterInNormalWarpWell`**).
2. For each such cell, adds **all four** cell edges in **React Flow space** (same integer **x** / **y** lines as the main coordinate grid).
3. **Deduplicates** edges shared by two well cells so each line is drawn once.

Cell geometry matches **`CoordinateGridOverlay`**: for map cell `(gx, gy)`, flow **y** runs from **`-(gy + 1)`** (top) to **`-gy`** (bottom); flow **x** runs from **`gx`** to **`gx + 1`**.

### 2.1 Zoom thresholds

Overlays compare React Flow viewport **`scale`** (pixels per flow unit; same value as the header **map zoom** and **`transform[2]`**):

| Overlay | Constant | Shown when |
|---------|----------|------------|
| Warp well grid | `WARP_WELL_OVERLAY_ZOOM_THRESHOLD` (= **5**) | `scale ≥ 5` |
| Full coordinate grid | `GRID_ZOOM_THRESHOLD` (= **15**) | `scale ≥ 15` |

The header shows **`Math.round(mapZoom * 100)%`**, so these correspond to about **500%** and **1500%** on the scale readout when that readout reflects the same zoom.

### 2.2 Stroke styling

- **Background grid:** `GRID_STROKE` -- `rgba(107, 114, 128, 0.3)` (gray at **30%** opacity) so it stays fainter than the well overlay when lines coincide.
- **Warp well:** `WARP_WELL_STROKE` -- `#78716c` (full opacity).

### 2.3 Render order

Inside **`MapGraph`** React Flow children: **`CoordinateGridOverlay`** first, then **`NormalWarpWellOutlinesOverlay`**, then planet dots and readout. The well lines paint above the faint background grid.

### 2.4 Viewport clipping

Warp segments are clipped to the visible flow rectangle (same bounds derivation as the grid) before mapping to pane pixels, so off-screen geometry does not produce huge SVG lines.

---

## 3. Tests

**Cross-language consistency:** [`test-fixtures/warp-well-consistency.json`](../test-fixtures/warp-well-consistency.json) holds golden **coordinate** and **cell** cases. Both implementations must agree:

- **`packages/api/tests/test_warp_well_consistency.py`** -- asserts `api.concepts.warp_well` against the fixture.
- **`packages/frontend/src/lib/warpWell.consistency.test.ts`** -- asserts `warpWell.ts` against the same file.

When changing rules, update the fixture once and fix any failing suite.

**`packages/frontend/src/lib/warpWell.test.ts`** additionally covers full-grid segments (internal shared edges), axis-aligned integer segments, and other UI-adjacent helpers.

**`packages/api/tests/test_warp_well_concepts.py`** covers concept behavior with sample turn data (independent of the shared fixture).

---

## 4. Changelog notes

When changing well rules or thresholds, update this doc and the [user guide](user-guide.md) map section so zoom behavior stays accurate for players. When changing **domain** rules, update **`api/concepts/warp_well.py`** first and keep **`warpWell.ts`** aligned (or drive the SPA from Core/BFF later).

---

## 5. Core API and BFF (analytics and future clients)

**Source of truth** for distance math is **`api.concepts.warp_well`**: `WarpWellKind`, `coordinate_in_warp_well`, `map_cell_indices_in_warp_well`, `planet_is_in_debris_disk`. No HTTP or storage inside `concepts/`.

**GameService** resolves a **`Planet`** from stored turn JSON by numeric **`planet_id`**, then calls those functions.

### 5.1 HTTP (mounted at `/api` on the root server)

| Method | Path (after `/api`) | Purpose |
|--------|----------------------|---------|
| `POST` | `/v1/games/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/coordinate-in-well` | Body: `planet_id`, `map_x`, `map_y`, `well_type` (`normal` \| `hyperjump`). Response: `{ "inside": bool }`. |
| `GET` | `/v1/games/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/cells` | Query: `planet_id`, `well_type`. Response: `{ "cells": [ { "x", "y" }, ... ] }` (map cell indices whose centers lie in the well). |

Unknown **`planet_id`** for that turn returns **404**.

### 5.2 BFF

Same paths under the BFF prefix (e.g. **`/bff/games/...`** when the BFF is mounted at `/bff`): handlers call **`GameService`** directly today so they can later be swapped for HTTP to Core without changing contracts.

### 5.3 Tests

- **`packages/api/tests/test_warp_well_concepts.py`** -- pure concept behavior.
- **`packages/api/tests/test_game_concepts_router.py`** -- Core routes.
- **`packages/bff/tests/test_games.py`** -- BFF warp-well routes.
