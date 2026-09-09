# Minefields map analytic

Map-only **turn analytic** (`analytic_id` `minefields`) that paints **known minefield**s from the shell turn’s `TurnInfo.minefields[]`. Locked product spec: [issue 288](https://github.com/SteveDraper/Planets-Console/issues/288). Glossary: **Minefields analytic**, **known minefield**, **minefield type**, **minefield pre-decay radius**, **minefield post-decay radius**, **minefield paint policy**, **minefield map pane**, **minefield hover** in [CONTEXT.md](../CONTEXT.md). Paint channel: [ADR 0030](adr/0030-minefield-map-pane.md).

Related: [Adding a turn analytic](design-adding-a-turn-analytic.md), [Stellar Cartography](design-stellar-cartography-analytic.md) (map-only + sidebar prefs), [map interaction surface](adr/0012-map-interaction-surface.md).

## Product

| Requirement | Decision |
|-------------|----------|
| Registration | Selectable, `supports_table=false`, `supports_map=true` |
| Data | Shell-turn `minefields[]` only; skip `units <= 0`; include `ishidden` without extra style |
| Availability | Grey when tabular **view mode** or `GameSettings.nominefields` (`This game has no minefields`). `minefieldsvisible` does **not** hide the analytic |
| Radii | Core: `preRadius = floor(sqrt(units))`; nebula keep `0.85` iff pre-decay disk intersects any RST nebula (`id >= 0`, `radius > 0`); else `0.95`; remaining `max(0, round(units * keep) - 1)`; `postRadius = floor(sqrt(remaining))` |
| Paint | Dedicated **minefield map pane** -- not `overlayCircles` or `regionOverlays` |
| Color | Per type: enable + **owner** vs **stance**. Owner always uses the per-player palette (overrides + preset), ignoring global **player color mode**. Stance: viewpoint own + inbound `relationfrom >= Safe Passage` vs everyone else |
| Hover | One descriptive contribution listing **all** overlapping enabled-type fields (smallest `preRadius`, then id). No click / context menu |
| Exports | Empty catalog ([#437](https://github.com/SteveDraper/Planets-Console/issues/437) owns queries) |

## Layers

- **Core** (`api/analytics/minefields.py`): facts only. Decay/radius/overlap in `api/concepts/minefield_decay.py`.
- **BFF**: passthrough map handler; table route validation error.
- **SPA** (`src/analytics/minefields/`): Zod wire, map merge, sidebar prefs (global localStorage), pane, hover contributor.

## Map pane (ADR 0030)

Z-order: cartography SVG < Visibility/homeworld **map region overlay**s < minefields pane < planet dots / fleet rings.

- Wrapper `isolation: isolate`. Fills `plus-lighter` (order-independent). Strokes second pass, source-over, sort by `id`. 1 CSS px strokes (pane-space `strokeWidth: 1`).
- Interior `0 → postRadius` fill 0.22; annulus `postRadius → preRadius` fill 0.10. Stale fills `× 0.55` (`infoTurn <` shell turn). Strokes opacity 0.9, not dimmed.
- Degenerate: equal radii → one dashed ring, no annulus; `postRadius == 0` → fill whole pre disk at annulus opacity, solid pre outline, no dashed ring.
- Coordinates: map cell **0.5** center offset (same as planets / cartography).

## Out of scope

Homeworld evidence, last-seen ledger, tabular tile, click/context menu, spatial exports (#437), dense/hardened decay (#438), global Crystal player palettes (#439), named MCP gameplay tools.
