# Stellar Cartography map rendering

How the console draws and interacts with **Stellar Cartography** on the React Flow starmap. Implementation plan and registration live in [design-stellar-cartography-analytic.md](design-stellar-cartography-analytic.md); this doc is the **appearance and interaction** spec for Phase 4.

**Code (target locations):**

| Area | Location |
|------|----------|
| Theme constants | `packages/frontend/src/lib/stellarCartographyTheme.ts` |
| SVG overlay builder | `packages/frontend/src/lib/stellarCartographyOverlay.ts` |
| Black hole pane shapes | `packages/frontend/src/lib/cartography/blackHoleOverlay.ts` |
| Map integration | `packages/frontend/src/components/MapGraph.tsx` |
| Wormhole edges | `packages/frontend/src/analytics/mapLayers.ts` (merge) + custom edge type if needed |
| Core map geometry | `packages/api/api/analytics/stellar_cartography.py` |
| Location sampling | `packages/api/api/concepts/` (ion storm, star cluster, black hole, nebula) |
| BFF map + sample routes | `packages/bff/bff/analytics/stellar_cartography.py`, `packages/bff/bff/routers/games.py` |

**Precedent:** [Warp wells on the map](design-warp-wells-map.md) (SVG pane, screen-stable strokes, game Y -> flow Y).

**Fixture:** game `673864`, turn `49` (`.data/games/673864/0/turns/49.json`).

---

## 1. Layer stack and z-order

| Concern | Rule |
|---------|------|
| **Planet dots** | Always on top of cartography (pane dots at `z-[5]`) |
| **Connection edges** | Strongest routing cue; cartography lines **lower contrast** than `#b1b1b7` connection edges (50% opacity) |
| **Cartography SVG pane** | Above coordinate grid, below planet dots |
| **SVG paint order** (bottom -> top) | Debris disk borders, nebulae, ion storms, star clusters, black holes |
| **Wormhole edges** | React Flow layer (not SVG); drawn with graph edges |
| **Zoom** | Cartography SVG and wormholes visible at **all** zoom levels (no cutoff or fade) |

**Client filter:** Only **enabled** cartography layers (persisted toggles) are drawn and included in hover sampling.

**Debris disk borders:** Planetoids (`debrisdisk == 1`) always render on the **base map**. The **Debris disk borders** cartography layer toggle draws **outline-only** circles for seed planets (`debrisdisk > 1`; radius in ly). No fill; no separate hover in v1.

---

## 2. Primitives by layer

All disc features use **fill + outline (C)**: soft semitransparent fill plus a slightly stronger rim. Strokes use **screen-stable** width `strokeWidth: 1 / scale` (same idea as connection edges in `MapGraph.tsx`).

Coordinates: map integer cells with **cell center offset** `0.5` when converting to flow space (same as planets and warp wells).

### 2.1 Nebulae

| Field | Use |
|-------|-----|
| `x`, `y`, `radius` | Circle |
| `name`, `intensity`, `gas` | Tooltip / future use; fill not scaled by `intensity` in v1 |

**Performance:** Cloud fill is rasterized **once per nebula name** in map space (capped at 512 px, grouped centers by `name`). Fill alpha is zero outside the analytic boundary polygon and where summed density is below the same **0.2** threshold as the outer boundary stroke. The displayed PNG is also clipped to the boundary path in SVG so scaled edges cannot bleed past the stroke. The boundary is an **analytic iso-contour** of that threshold (512 polar rays). Pan/zoom reprojects the cached PNG and recomputes the boundary path (`nebulaCloudOverlay.ts`).

### 2.2 Ion storms

Grouped by root storm (`parentId`). Fill is rasterized by **hazard class at each cell** (summed voltage in cloudy mode, flat center voltage in classic mode). Class boundaries and the outer edge use **ray-marched iso-contours**: a coarse grid finds each disjoint region at a threshold, then one smooth 512-ray polygon is traced from an interior anchor per region (same approach as nebula outer boundaries). Thresholds: 50 / 100 / 150 / 200 meV between classes; outer edge at voltage > 0. One movement arrow per root storm.

**Fill opacity:** `0.15 * class` where **class** is 1..5 from wiki voltage tiers:

| Class | Name | Voltage |
|-------|------|---------|
| 1 | Harmless | under 50 (`voltage < 50`) |
| 2 | Moderate | 50--99 |
| 3 | Strong | 100--149 |
| 4 | Dangerous | 150--199 |
| 5 | Very dangerous | 200 and up |

Boundaries: `>= 50` -> 2; `>= 100` -> 3; `>= 150` -> 4; `>= 200` -> 5. Emit **`class`** on each overlay primitive for tests.

**Movement arrow:** From center, direction = `heading` (confirm host convention in implementation: typically 0 = north, clockwise). Length in map ly = **`warp`** (ly per turn). Arrow scales with map zoom like geometry.

**Colors:** See [section 3](#3-color-theme); stroke and arrow hue warm with class 4--5.

### 2.3 Star clusters

One circle per `stars[]` body at `radius`. Bodies sharing `name` are one cluster; circles may overlap.

### 2.4 Black holes

**C** with lethal **core** (`coreradius`) and nine **ergosphere bands** spanning `coreradius + 9 * bandradius` ly (see analytic doc). Map overlay adds a cosmetic **+5 ly** cyan halo beyond the outer band.

**Rendering:** One SVG group per hole (`BlackHoleOverlay`): bottom circle uses a halo radial gradient (transparent inside the ergosphere, cyan at the edge, fading outward); top circle uses an ergosphere radial gradient with hard stops at each band boundary (grey ramp from `blackHoleErgosphereBandGrey`, composited at `BLACK_HOLE_ERGOSPHERE_BAND_OPACITY`). Pane shapes are built in `blackHoleOverlay.ts`, not as nine generic masked annuli.

### 2.5 Debris disk borders

| Field | Use |
|-------|-----|
| Planet `x`, `y`, `debrisdisk` | Seed planet only (`debrisdisk > 1`): circle center and radius (ly) |
| `name`, `planetId` | Optional metadata; no v1 hover |

**Render:** Outline only (`fill: none`), red stroke (`#dc2626`, 1px pane space), painted **above** other cartography annuli. Planetoids inside the disk remain base-map nodes.

### 2.6 Wormholes

See [section 5](#5-wormholes).

---

## 3. Color theme

Defined in `stellarCartographyTheme.ts`.

| Layer | Fill | Rim / line |
|-------|------|------------|
| **Nebulae** | `#6366f1` indigo, soft alpha | Same hue, higher rim alpha (~60% stroke) |
| **Star clusters** | `#f97316` orange | Same |
| **Black holes** | Core `#0f0f12`; band low-alpha `#7c3aed` | Band rim `#7c3aed` |
| **Debris disk borders** | -- | `#dc2626` red outline |
| **Wormholes** (line) | -- | `#38bdf8` sky |
| **Wormholes** (unknown target) | Entrance dot 6px `#38bdf8` | No line |

**Ion storms:**

| Class | Fill opacity | Stroke / arrow |
|-------|--------------|----------------|
| 1--3 | 15%, 30%, 45% | `#eab308` amber |
| 4 | 60% | `#f97316` orange |
| 5 | 75% | `#ef4444` red |

Rim stroke opacity: 60% for classes 1--3; 80% for 4--5.

---

## 4. Hover tooltips

### 4.1 Stacked sampling

On pointer move, convert to **map coordinates** (same as the map coordinate readout). Collect **every** enabled feature that applies at that cell -- **not** only the topmost SVG shape.

**Single tooltip panel**, blocks in paint order:

1. Nebula
2. Ion storm
3. Star cluster
4. Black hole
5. Wormhole (if pointer on wormhole hit target)

Example:

```
Nebula Zoie
Ion storm: Class 3 Strong — 112 V
Star cluster Cirius — radiation 42
Black hole: Lethal (Solace)
```

Typography: consistent with route waypoint labels (`font-mono`, dark background strip).

### 4.2 Per-layer lines

| Layer | Tooltip |
|-------|---------|
| **Nebula** | Name when pointer inside `radius` |
| **Ion storm** | Class name + **voltage at cell** (not only center field) |
| **Star cluster** | Name + **radiation at cell** |
| **Black hole** | Inside core: **`Lethal`** (+ name). In band (`coreradius`..`bandradius`): **`Max warp: N`**. Outside: omit |
| **Wormhole** | See [section 5](#5-wormholes) |

### 4.3 Core game concepts + BFF batch route

Host-aligned math lives in **`packages/api/api/concepts/`** (no duplicated formulas in TypeScript).

**Preferred API:**

- Core: `GET /api/v1/games/{game_id}/{perspective}/turns/{turn_number}/concepts/stellar-cartography/sample?x=&y=`
- BFF: `GET /bff/games/.../turns/{turn}/concepts/stellar-cartography/sample?x=&y=`

Response shape (illustrative):

```json
{
  "x": 1600,
  "y": 2511,
  "entries": [
    { "layer": "ion-storms", "lines": ["Class 3 Strong", "112 V"] },
    { "layer": "nebulae", "lines": ["Zoie"] }
  ]
}
```

SPA: debounce ~100ms; only when stellar-cartography (or relevant layers) enabled.

| Quantity | Sampled at `(x, y)` |
|----------|---------------------|
| Ion voltage | Position-dependent in cloudy storms (wiki) |
| Star radiation | Distance / halo rules from cluster bodies |
| Black hole max warp | Ergosphere band only; core returns lethal, not a number |

**Phase split:** Phase 4a can ship static geometry + wormhole UX; Phase 4b wires batched sample + stacked tooltip.

---

## 5. Wormholes

### 5.1 Geometry

| Case | Draw |
|------|------|
| **Known target** | Straight edge entrance `(x,y)` -> `(targetx, targety)` |
| **Unknown target** | 6px sky dot at entrance only; no edge |

Classify in Core or BFF:

- **Bidirectional:** another record inverts endpoints. Emit **one** edge per unordered pair (dedupe; turn 49 has 112 records -> 56 lines).
- **Mono-directional:** no reverse record. Edge with **arrowhead** at target end.

**Wire fields:** `id`, `x`, `y`, `targetx`, `targety`, `stability`, `name`, `isBidirectional`, optional `partnerId`.

React Flow node ids: `stellar-cartography:wh-{id}` (minimal/invisible nodes for routing).

### 5.2 Interaction

Requires `pointer-events` on wormhole hit targets (cartography SVG stays `pointer-events-none`).

| Gesture | Behavior |
|---------|----------|
| **Click** end with known other end | `setViewport` to center other end; **keep zoom** |
| **Hover** (bi or mono entrance) | `goes to (targetx, targety)` |
| **Hover** (mono exit only) | `exit - entrance at (x, y)` for entrance coords |

Include wormhole block in stacked tooltip when the pointer hits the wormhole edge/node.

### 5.3 Edge styling

Sky `#38bdf8`, 1px screen-stable, opacity below connection edges. Bidirectional: plain line. Mono: arrowhead at target.

---

## 6. Map analytic wire shape (geometry)

BFF `GET /bff/analytics/stellar-cartography/map` (illustrative):

```ts
type StellarCartographyMapResponse = {
  analyticId: 'stellar-cartography'
  overlayCircles: Array<{
    layer: 'nebulae' | 'ion-storms' | 'star-clusters' | 'black-holes'
    id: string
    x: number
    y: number
    radius: number
    // ion: class, heading, warp, parentid, centerVoltage
    // black hole: coreradius, bandradius
    // nebula: name, intensity, gas
    // star: name, ...
  }>
  nodes: Array<{ id: string; x: number; y: number }>
  edges: Array<{
    source: string
    target: string
    isBidirectional: boolean
    stability?: number
    name?: string
  }>
}
```

`combineMapData` prefixes ids with `stellar-cartography:` and merges edges into `CombinedMapData`. `overlayCircles` ride on `CombinedMapData` for `stellarCartographyOverlay.ts`.

---

## 7. Implementation checklist (Phase 4)

**4a -- Geometry and wormholes**

- [ ] `stellarCartographyOverlay.ts` draws circles, annuli, ion arrows
- [ ] `stellarCartographyTheme.ts` colors and class -> opacity
- [ ] `MapGraph` pane; all zoom levels; paint order
- [ ] Wormhole merge + custom edge; click recenter; wormhole-only hover strings
- [ ] Unit tests: flow projection, class boundaries, bi/mono dedupe

**4b -- Stacked hover sampling**

- [ ] Core concept `sample_at(turn, x, y)` for all layers
- [ ] BFF + Core batch sample routes
- [ ] MapGraph tooltip UI; debounced fetch
- [ ] Concept tests against fixture turn

**Docs:** User guide map subsection when 4a/4b stable.

---

## 8. Design decisions (rendering)

| # | Topic | Choice |
|---|--------|--------|
| R1 | Disc primitive | Fill + outline per layer |
| R2 | Ion opacity | 15% x wiki class (1--5) |
| R3 | Ion stroke | Warmer hue for class 4--5 |
| R4 | Ion motion | Arrow: `heading`, length `warp` ly |
| R5 | Wormholes | Known line / unknown dot; bi vs mono |
| R6 | Wormhole UX | Click recenter; hover copy |
| R7 | Debris disk borders | Outline-only layer; planetoids always on base map |
| R8 | Colors | Theme table + ion class shift |
| R9 | Hover | Stacked; all layers at cell |
| R10 | Formulas | Core concepts + batch sample |
| R11 | Black hole tooltip | Lethal in core; max warp in band |
| R12 | Zoom | Always on |
| R13 | Paint order | Debris disk borders -> nebulae -> ion -> stars -> black holes |
