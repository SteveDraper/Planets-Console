# Dedicated minefield map pane

The **Minefields analytic** paints per-field disks with owner/stance colors, concentric pre/post-decay rims, and commutative overlap. That is not **map region overlay** coverage/boundary (Visibility / homeworld) and not Stellar Cartography `overlayCircles` (filtered by **Cartography layer**).

**Decision:** emit field facts on the minefields map payload and blit them in a dedicated MapGraph SVG pane (`isolation: isolate`, fill `plus-lighter`, 1px screen-stable strokes source-over after fills). Do not add a third shared geometry discriminant to `regionOverlays` or reuse `overlayCircles`.

**Considered:** `overlayCircles` with extra layer ids (cartography policy would have to ignore them; per-field player colors still do not fit layer theming); `regionOverlays` annulus geometry (extends ADR 0008, but fill color is per field from **player color** / stance prefs, not a kind default). Fleet already has a dedicated pane for the same reason.

Glossary: **Minefield map pane** in [CONTEXT.md](../../CONTEXT.md). Ticket: [Add display of minefields](https://github.com/SteveDraper/Planets-Console/issues/288).
