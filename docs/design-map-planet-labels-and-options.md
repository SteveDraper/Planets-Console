# Map planet labels and display options

This document describes the **map options** UI and **planet hover/pin labels** on the React Flow map: controls in the bottom sheet, label content by detail level, how host sentinels drive **data availability**, masking rules, and interaction behavior.

**Code (primary):**

| Area | Location |
|------|----------|
| Map options shell (bottom sheet, toggle) | `packages/frontend/src/components/MapPaneWithDisplayControls.tsx` |
| Planet info controls (checkboxes + detail level) | `packages/frontend/src/components/PlanetMapInfoControls.tsx` |
| Label model (options, availability, title line, minerals) | `packages/frontend/src/components/planetMapLabelModel.ts` |
| Label rendering | `packages/frontend/src/components/PlanetMapLabel.tsx` |
| Map graph (dots, overlay, hover, pin, grid) | `packages/frontend/src/components/MapGraph.tsx` |
| Wiring + combined map data | `packages/frontend/src/components/MainArea.tsx` |
| BFF map node normalization | `packages/frontend/src/api/bff.ts` (`normalizeMapDataResponse`, `normalizeMapNode`) |

Related: base-map data flow and node shape are summarized in [design-issue-10-base-map-from-core.md](design-issue-10-base-map-from-core.md). Shell state split (where `planetLabelOptions` lives) follows [design-frontend-and-backend-state.md](design-frontend-and-backend-state.md).

---

## 1. Map options panel

In **map mode**, the main area wraps the map in **`MapPaneWithDisplayControls`**: a **bottom sheet** (right half of the map) titled **Map options**, toggled with **Show map options** / **Hide map options**. The sheet contains arbitrary **`controls`** content; today that is **`PlanetMapInfoControls`**.

Planet label settings are **React state in `MainArea`** (`planetLabelOptions`) and are passed into **`MapGraph`** as props. They are not persisted to local storage.

---

## 2. Planet info controls (`PlanetMapInfoControls`)

### 2.1 Title line toggles (checkboxes)

Three independent checkboxes control which parts appear in the **single title line** of a planet label (space-separated):

| Control | Field | Default |
|---------|--------|---------|
| Planet id | `includePlanetId` | on |
| Planet name | `includePlanetName` | off |
| Coordinates | `includeCoordinates` | off |

If **none** of these are enabled, **no** hover/pin label is shown (there is nothing to render in the title line). This is enforced by `planetLabelOptionsShowAnyLabel` in `planetMapLabelModel.ts`.

Layout: checkboxes are on **one row** when width allows (`flex-wrap`); the **Detail level** label and dropdown sit on **one line** next to each other.

### 2.2 Detail level (`detailsLevel`)

Dropdown labeled **Detail level** (native `<select>`). Values and tooltips (`title` on the select and options):

| Value | Meaning |
|-------|---------|
| **None** | Title line only (no properties block below). |
| **Low** | Structured **basic** block: temperature, natives line, ownership, colonist clans. |
| **Medium** | **Low** block plus **mineral table** (surface / ground / density per mineral), when data allows (see §4). |
| **Debug** | Full **raw** sections: complete low block, mineral table, then remaining planet JSON keys (excluding keys already shown in low/medium). No masking by availability (see §5). |

Type: `PlanetDetailsLevel` = `'none' | 'low' | 'medium' | 'debug'`.

Defaults: id only in the title; **Detail level** = **None**.

---

## 3. Map rendering and layering (`MapGraph`)

- **React Flow** draws invisible routing nodes and edges; **planet dots** and **labels** are drawn in a **fixed-size screen-space overlay** so dots stay a constant pixel size while zooming.
- The overlay sits in a sibling layer **above** `.react-flow__renderer` (z-index) so edges/nodes do not paint over labels.
- **Dots** are rendered in one layer; **labels** in a second layer **above** dots so nearby planets’ dots never cover another planet’s label.
- When zoom exceeds a threshold, a **coordinate grid** (integer map lines) is drawn; a **Panel** shows floored map coordinates and zoom in the bottom-left.

---

## 4. Data on map nodes and ownership

Combined map nodes (after prefixing by analytic id in `MainArea.combineMapData`) may include:

- **`planet`**: optional JSON object from the BFF (turn snapshot fields for that body).
- **`ownerName`**: optional resolved display name for `ownerid` when the BFF provides it.

The BFF normalizes each node so `planet` / `ownerName` are not dropped by reference sharing (`normalizeMapDataResponse` in `bff.ts`). TanStack Query uses a stable key and `structuralSharing: false` for map queries so merged `planet` payloads stay visible.

---

## 5. Planet data availability (`getPlanetDataAvailability`)

Labels use a **four-state** availability (not a single boolean) derived from host sentinels on **`temp`**, **`ownerid`**, and **surface `neutronium`**:

| State | Rule (evaluated in implementation order) |
|-------|------------------------------------------|
| **NO_DATA** | Unowned (`ownerid` missing, `null`, or `0`) **and** finite **`temp` &lt; 0**; or missing planet; or fallthrough when signals are insufficient. |
| **OWNERSHIP_ONLY** | **Owned** (non-zero owner) **and** finite **`temp` &lt; 0**. |
| **BASIC_INFO** | Finite **`temp` ≥ 0** **and** finite **surface `neutronium` &lt; 0** (basic scan, no reliable mineral breakdown). |
| **FULL_INFO** | Finite **surface `neutronium` ≥ 0** (full scan including minerals). |

**Note:** If **`temp` &lt; 0** (unowned vs owned branch), availability is determined **without** using neutronium; that matches “no temperature yet” vs “owned but unscanned” semantics.

---

## 6. Masking vs detail level (non-debug)

For **`detailsLevel` other than `debug`**, the **properties** section is **masked** by availability:

| Availability | What is shown (properties) |
|--------------|------------------------------|
| **NO_DATA** | Single line: **Unknown**. |
| **OWNERSHIP_ONLY** | **Ownership** line only. |
| **BASIC_INFO** | Temperature, natives, ownership, colonist clans (same structured fields as full low block). |
| **FULL_INFO** | Full **low** block (all four groups). |

**Medium** detail level:

- Adds the **mineral table** only when availability is **FULL_INFO** (surface/ground/density; density values are shown as **percentages** with a **`%`** suffix).
- For **BASIC_INFO**, **medium** shows the same masked content as **low** (no mineral table), because minerals are not considered reliable until **FULL_INFO**.

**Debug** ignores masking: always shows full low block, mineral table, and the debug key/value list.

---

## 7. Hover vs pinned labels

- **Hover**: label appears when the pointer is within a fixed **pixel radius** of a planet dot (hit test uses a spatial grid in map coordinates), only if at least one title-line option is enabled and **Detail level** is not **None**.
- **Pin**: primary **click** on a planet (within the same hit radius) **pins** that planet’s label. Clicking the **same** planet again unpins. Clicking **another** planet switches the pin. **Escape** clears the pin.
- While pinned, **hover** labels for **other** planets are suppressed.
- Clicking the **map background** where **no** planet is within the hit radius **unpins** (returns to hover-only behavior).
- Pinned label panel uses **`pointer-events: auto`** and **`stopPropagation`** on the label so interacting with the panel does not dismiss the pin unintentionally.

---

## 8. Display conventions

- **Natives:** Host may send `nativeracename: "none"` and `nativeclans: -1`. The UI shows **`Natives: None`** when both resolve to none; otherwise negative clan counts display as **None** for the count, and the literal **none** race string as **None**.
- **Mineral densities** in the table are **percentages** and render with a **`%`** suffix.
- **Unknown / sentinel** handling for title and structured lines follows the availability model above rather than a single `isUnknown` flag.

---

## 9. Query / cache notes

Map fetches use the `['analytic', id, 'map', scope]` pattern with a **version segment** (e.g. `'planet'`) in the key where needed so merged node payloads refetch when the contract changes. See [design-frontend-and-backend-state.md](design-frontend-and-backend-state.md).
