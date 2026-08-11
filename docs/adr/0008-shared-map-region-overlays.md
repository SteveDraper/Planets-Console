# Shared map region overlays (coverage vs boundary)

Status: accepted

## Context

Map analytics need a shared way to paint shaded regions on the combined map. Visibility already emits hybrid **coverage** footprints (ideal disks plus nebula-local patches) on the shared wire field `regionOverlays`. Homeworld locator ([#35](https://github.com/SteveDraper/Planets-Console/issues/35)) needs annular sectors (closed paths with circular arcs) plus optional envelope disks, annotations (`isPinned`, status, candidate count, pinned player identity), and a per-analytic display-mode preference -- without inventing a parallel homeworld-only wire field or reusing cartography `overlayCircles`.

Without an explicit geometry discriminant and display-policy split, MapGraph would treat every `regionOverlays` entry as Visibility-owned (kind toggles / color prefs), and Core would either overload coverage blobs for arcs or grow a second overlay channel.

**Architecture constraint:** Core must not emit UI semantics (English hover prose, display templates). Shared overlay annotations are domain/machine facts only; the SPA (preferred) or BFF formats user-facing strings.

## Decision

- **`regionOverlays` is analytic-agnostic.** Any map analytic may merge entries. Style metadata (`kind`, `id`, `fillColor`, `fillOpacity`) travels with the geometry.
- **Geometry is discriminated:**
  - **`coverage`** -- hybrid disks + nebula-local patches (Visibility and other coverage footprints). Core owns coverage truth; the SPA blits.
  - **`boundary`** -- closed ordered vertices with per-edge `line` | `arc` (map-space clockwise on arcs). Optional colocated envelope **disks** on the same entry (e.g. 81/162 LY homeworld envelopes). Suitable for annular sectors. When a closed path is not needed, **disks-only** boundary entries (empty vertices/edges + non-empty disks) are allowed for planet-centered envelopes.
- **Optional shared annotations** on any overlay are **domain/machine facts only**: `isPinned`, `status`, `candidateCount`, `playerLabel` (roster identity, not a sentence), plus homeworld ownership evidence when emitted (`possibleOwners` with provenance kinds/counts, and `ownershipWinningStrength` when the projected owner set is unique -- ADR 0010). Analytics that do not use them omit the fields. **UI copy** (hover tooltip lines, labels) is assembled by the **client** (preferred) or BFF from those facts -- Core does not emit English `hoverSummary` or other presentation strings.
- **Per-analytic display policy stays on the client.** Visibility kind enablement and base colors apply only to Visibility region kinds. Homeworld region display mode (and future analytic filters) own their own preference stores. MapGraph must not run non-Visibility overlays through Visibility preference mutation beyond pass-through.
- Distinct from Stellar Cartography hazard circles (`overlayCircles`).

## Consequences

- Wire and FE normalize round-trip both geometry variants; legacy flat disks+patches without a discriminant may still normalize as coverage during transition.
- Homeworld sector emission (#35 later phases) reuses this primitive; no homeworld-only overlay field.
- New map-region consumers extend `kind` + client preference policy rather than inventing parallel geometry channels.
- Hover and other display strings stay out of Core; changing tooltip wording does not require a Core API change when facts are already on the wire.
- Glossary: **Map region overlay**, **Homeworld region overlay**, **homeworld region display mode**, **homeworld layout distribution asset** in [CONTEXT.md](../../CONTEXT.md).

See also: [design-homeworld-locator-analytic.md](../design-homeworld-locator-analytic.md) §4.2 / §11.
