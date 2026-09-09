import { describe, expect, it } from 'vitest'
import {
  MAP_PANE_Z_INDEX,
  mapPaneZClass,
  type MapPaneZBand,
} from './mapPaneZOrder'

const BANDS = Object.keys(MAP_PANE_Z_INDEX) as MapPaneZBand[]

describe('MAP_PANE_Z_INDEX', () => {
  it('orders cartography < region overlays < minefields < planet dots < fleet location rings', () => {
    expect(MAP_PANE_Z_INDEX.cartography).toBeLessThan(MAP_PANE_Z_INDEX.regionOverlays)
    expect(MAP_PANE_Z_INDEX.regionOverlays).toBeLessThan(MAP_PANE_Z_INDEX.minefields)
    expect(MAP_PANE_Z_INDEX.minefields).toBeLessThan(MAP_PANE_Z_INDEX.planetDots)
    expect(MAP_PANE_Z_INDEX.planetDots).toBeLessThan(MAP_PANE_Z_INDEX.fleetLocationRings)
  })

  it('keeps planet dots above minefield and region fills', () => {
    expect(MAP_PANE_Z_INDEX.planetDots).toBeGreaterThan(MAP_PANE_Z_INDEX.minefields)
    expect(MAP_PANE_Z_INDEX.planetDots).toBeGreaterThan(MAP_PANE_Z_INDEX.regionOverlays)
  })

  it('keeps fleet chrome at or above planet dots and above minefields', () => {
    expect(MAP_PANE_Z_INDEX.fleetLocationRings).toBeGreaterThan(MAP_PANE_Z_INDEX.planetDots)
    expect(MAP_PANE_Z_INDEX.fleetHeadingTrails).toBeGreaterThanOrEqual(
      MAP_PANE_Z_INDEX.planetDots
    )
    expect(MAP_PANE_Z_INDEX.fleetHeadingTrails).toBeGreaterThan(MAP_PANE_Z_INDEX.minefields)
  })

  it('keeps warp-well / grid cartography band below region fills', () => {
    expect(MAP_PANE_Z_INDEX.cartography).toBeLessThan(MAP_PANE_Z_INDEX.regionOverlays)
  })

  it('keeps homeworld markers at or above planet dots', () => {
    expect(MAP_PANE_Z_INDEX.homeworldMarkers).toBeGreaterThanOrEqual(
      MAP_PANE_Z_INDEX.planetDots
    )
  })

  it('spells each band as a Tailwind z-[N] class', () => {
    for (const band of BANDS) {
      expect(mapPaneZClass(band)).toBe(`z-[${MAP_PANE_Z_INDEX[band]}]`)
    }
  })
})
