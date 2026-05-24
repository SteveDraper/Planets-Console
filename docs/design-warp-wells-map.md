# Warp wells on the map

This document describes how the console models **warp wells** in code: **Core API** (`api.concepts`), **HTTP** (turn-scoped routes), **BFF** (base-map batch + concept routes), and the **React Flow** map (grid overlays, zoom thresholds).

**Code (primary):**

| Area | Location |
|------|----------|
| Well rules (Python, single module) | `packages/api/api/concepts/warp_well.py` |
| Turn lookup + service API | `packages/api/api/services/turn_concept_service.py` |
| Base-map batch cells | `packages/api/api/analytics/base_map.py` (`normalWellCells` per node) |
| Core REST routes | `packages/api/api/routers/game_concepts.py` |
| HTTP request/response shapes | `packages/api/api/transport/concept_warp_well.py` |
| BFF mirror routes | `packages/bff/bff/routers/games.py` |
| Frontend (render only) | `packages/frontend/src/lib/warpWellOverlay.ts` (overlay entry: `buildWarpWellOverlayPaneLines`), `packages/frontend/src/lib/warpWell.ts` (cell normalization and grid segments), `MapGraph.tsx` |
| Planet `debrisdisk` on map nodes | Turn snapshot on `MapNode.planet` (see `packages/frontend/src/api/bff.ts` normalization) |

Related domain context: [vga-planets-domain-context.md](vga-planets-domain-context.md) (tactics / routing). This doc is about **console behavior**, not host rules.

---

## 1. Warp well module (`api.concepts.warp_well`)

Two logical well kinds for **canonical geometry** (map overlay, concept HTTP):

| Type | Rule (Cartesian / Euclidean in map coordinates) |
|------|--------------------------------------------------|
| **normal** | Distance from planet map cell index to query point is **≤ 3** |
| **hyperjump** | Same distance is **strictly &lt; 3** |

Distance is **`hypot(Δx, Δy)`** on the map plane. A non-debris **normal** well contains exactly **29** map cells.

**Debris disk:** Non-zero **`debrisdisk`** means no extended well for map/concept geometry (empty **`normalWellCells`** on base-map nodes). Reachability uses a point-only well at the planet cell; see **`point_in_reachability_well`** / **`min_distance_to_reachability_well`** (same module, fast path for Connections).

Canonical helpers:

- **`coordinate_in_warp_well`**, **`map_cell_indices_in_warp_well`**
- **`point_in_reachability_well`**, **`min_distance_to_reachability_well`**

---

## 2. Map visualization (normal well only)

Only the **normal** well is drawn today. Cell lists are **precomputed on the server** and included on each base-map node as **`normalWellCells`** (batch fetch with the starmap). The SPA does not recompute well geometry.

The overlay:

1. Reads **`normalWellCells`** from each map node (empty for debris-disk planets).
2. For each cell, adds **all four** cell edges in **React Flow space** (same integer **x** / **y** lines as the main coordinate grid).
3. **Deduplicates** edges shared by two well cells so each line is drawn once.

The overlay pipeline starts in **`warpWellOverlay.ts`**: **`buildWarpWellOverlayPaneLines`** reads each node’s **`normalWellCells`**, clips segments to the viewport, and returns pane-pixel lines for **`MapGraph`**. Lower-level helpers in **`warpWell.ts`** (`normalizeWarpWellMapCells`, `normalWellGridSegmentsFromNormalizedWellCells`, etc.) turn server-provided cells into deduplicated flow-space segments; they do not recompute well geometry.

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

**Golden fixture:** [`test-fixtures/warp-well-consistency.json`](../test-fixtures/warp-well-consistency.json) holds coordinate and cell cases for **`api.concepts.warp_well`** (`test_warp_well_consistency.py`).

**`packages/frontend/src/lib/warpWell.test.ts`** covers cell normalization, segment deduplication, and bounding-box helpers.

**`packages/frontend/src/lib/warpWellOverlay.test.ts`** covers **`buildWarpWellOverlayPaneLines`** (viewport clipping and zoom threshold).

**`packages/api/tests/test_warp_well_concepts.py`** covers concept behavior, reachability equivalence, and the fixed normal-well cell count.

---

## 4. Changelog notes

When changing well rules or thresholds, update this doc and the [user guide](user-guide.md) map section. Change **`api/concepts/warp_well.py`** first; base-map and concept routes follow automatically.

---

## 5. Core API and BFF

**Source of truth** for well math is **`api.concepts.warp_well`**. No HTTP or storage inside `concepts/`.

**TurnConceptService** resolves a **`Planet`** from stored turn JSON by numeric **`planet_id`**, then calls those functions.

### 5.1 Base-map batch delivery

**`GET /bff/analytics/base-map/map`** (and Core **`.../analytics/base-map`**) returns each planet node with **`normalWellCells`**: `[{ "x", "y" }, ...]`. Loaded with the starmap regardless of zoom; the overlay renders only above the zoom threshold.

### 5.2 Per-planet concept HTTP (mounted at `/api` on the root server)

| Method | Path (after `/api`) | Purpose |
|--------|----------------------|---------|
| `POST` | `/v1/games/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/coordinate-in-well` | Body: `planet_id`, `map_x`, `map_y`, `well_type` (`normal` \| `hyperjump`). Response: `{ "inside": bool }`. |
| `GET` | `/v1/games/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/cells` | Query: `planet_id`, `well_type`. Response: `{ "cells": [ { "x", "y" }, ... ] }`. Use for hyperjump or ad hoc clients; map overlay uses base-map normal cells. |

Unknown **`planet_id`** for that turn returns **404**.

### 5.3 BFF concept mirror

Same concept paths under **`/bff/games/...`** via **`CoreClient`** (shared handlers with Core REST).

### 5.4 Connections analytic (reachability)

**Reachability** helpers in **`warp_well.py`** drive **`planet_connections`**: direct edges, flare arrival tests, and spatial pruning. The Connections map analytic does **not** draw well outlines. See [design-connections-analytic.md](design-connections-analytic.md).

### 5.5 Tests

- **`packages/api/tests/test_warp_well_concepts.py`** -- pure concept + reachability behavior.
- **`packages/api/tests/test_game_concepts_router.py`** -- Core routes.
- **`packages/bff/tests/test_games.py`** -- BFF warp-well concept routes.
