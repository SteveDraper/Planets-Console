import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { resolveHomeworldSelectedSectorIndex } from './resolveHomeworldSelectedSectorIndex'

function sectorOverlay(index: number, originX = 0, originY = 0): MapRegionOverlay {
  return {
    kind: 'homeworld-sector',
    id: `homeworld-sector-${index}`,
    fillColor: '#f97316',
    fillOpacity: 0,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: originX, y: originY },
        { x: originX + 1, y: originY },
        { x: originX + 1, y: originY + 1 },
        { x: originX, y: originY + 1 },
      ],
      edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }, { type: 'line' }],
    },
  }
}

describe('resolveHomeworldSelectedSectorIndex', () => {
  it('returns null when nothing is selected', () => {
    expect(
      resolveHomeworldSelectedSectorIndex(null, [{ planetId: 1, x: 0.5, y: 0.5 }], [
        sectorOverlay(0),
      ])
    ).toBeNull()
  })

  it('returns sectorIndex for sector selection', () => {
    expect(
      resolveHomeworldSelectedSectorIndex(
        { kind: 'sector', sectorIndex: 3 },
        [],
        [sectorOverlay(3)]
      )
    ).toBe(3)
  })

  it('returns sectorIndex even when that sector overlay is absent', () => {
    expect(
      resolveHomeworldSelectedSectorIndex({ kind: 'sector', sectorIndex: 7 }, [], [])
    ).toBe(7)
  })

  it('resolves planet selection via marker hit-test against overlays', () => {
    const overlays = [sectorOverlay(0), sectorOverlay(2, 10, 10)]
    expect(
      resolveHomeworldSelectedSectorIndex(
        { kind: 'planet', planetId: 42 },
        [{ planetId: 42, x: 10.5, y: 10.5 }],
        overlays
      )
    ).toBe(2)
  })

  it('returns null when selected planet has no marker', () => {
    expect(
      resolveHomeworldSelectedSectorIndex(
        { kind: 'planet', planetId: 99 },
        [{ planetId: 1, x: 0.5, y: 0.5 }],
        [sectorOverlay(0)]
      )
    ).toBeNull()
  })

  it('returns null when planet marker falls outside all sector overlays', () => {
    expect(
      resolveHomeworldSelectedSectorIndex(
        { kind: 'planet', planetId: 1 },
        [{ planetId: 1, x: 50, y: 50 }],
        [sectorOverlay(0)]
      )
    ).toBeNull()
  })
})
