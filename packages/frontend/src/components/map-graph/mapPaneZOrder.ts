/**
 * Named z-index stack for MapGraph overlay panes.
 * Integers increase toward the viewer:
 * cartography (SVG, warp wells, coordinate grid)
 * < region overlays (Visibility / homeworld fills)
 * < minefields
 * < planet dots (homeworld markers sit in this band)
 * < fleet chrome (heading trails and location rings)
 */

export const MAP_PANE_Z_INDEX = {
  cartography: 5,
  regionOverlays: 6,
  minefields: 7,
  planetDots: 8,
  homeworldMarkers: 8,
  fleetHeadingTrails: 9,
  fleetLocationRings: 9,
} as const

export type MapPaneZBand = keyof typeof MAP_PANE_Z_INDEX
type MapPaneZValue = (typeof MAP_PANE_Z_INDEX)[MapPaneZBand]

/** Complete `z-[N]` literals so Tailwind JIT emits the stack values. */
const MAP_PANE_Z_TAILWIND = {
  5: 'z-[5]',
  6: 'z-[6]',
  7: 'z-[7]',
  8: 'z-[8]',
  9: 'z-[9]',
} as const satisfies Record<MapPaneZValue, `z-[${number}]`>

export function mapPaneZClass(band: MapPaneZBand): `z-[${number}]` {
  return MAP_PANE_Z_TAILWIND[MAP_PANE_Z_INDEX[band]]
}
