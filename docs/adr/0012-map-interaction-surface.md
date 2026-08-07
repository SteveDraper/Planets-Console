# Map interaction surface owns pane pointer composition

Under **map mode**, hover (and later click / context-menu) must not be implemented as per-overlay mouse capture. The SPA uses a **map interaction surface**: one pane pointer owner, mount-scoped **map interaction contributor**s, typed hover blocks, and a **map hover composition policy** keyed by **map hover contribution kind** (`descriptive` vs `map-element`) with `yieldsTo` / `mergesWith` / `stacksWith`. Paint **map layer**s stay pointer-event transparent.

**Considered:** hover-only manager (rejected -- invites a parallel click manager); policy keyed only by analytic id (rejected -- one analytic can emit descriptive and map-element contributions); folding peer descriptive panels into a separate `stacksWith` (rejected for descriptive content -- use `mergesWith` with titled sections; keep `stacksWith` for map-element chrome).

**Consequences:** Migrate planet, fleet, region, and cartography descriptive hover onto the surface before adding click/menu contributors. Reclassifying wormhole affordances as **map-element** contributions is a separate hover follow-on; full click/context-menu migration is a further ticket that may need more grilling.
