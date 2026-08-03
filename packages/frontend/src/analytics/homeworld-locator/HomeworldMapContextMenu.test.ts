import { describe, expect, it } from 'vitest'
import { isEventInsideHomeworldMenu } from './HomeworldMapContextMenu'
import {
  resolveOwnershipAssertTargetForPlanet,
  resolveOwnershipAssertTargetForSector,
} from './resolveOwnershipAssertTarget'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'

/**
 * Context-menu handler resolution (planet vs sector) without mounting React Flow.
 */
describe('homeworld map context menu target resolution', () => {
  const sector: MapRegionOverlay = {
    kind: 'homeworld-sector',
    id: 'homeworld-sector-1',
    fillColor: '#f97316',
    fillOpacity: 0,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 10 },
        { x: 0, y: 10 },
      ],
      edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }, { type: 'line' }],
    },
  }

  it('builds a planet menu ownership target when the planet sits in a sector', () => {
    const ownership = resolveOwnershipAssertTargetForPlanet([sector], 44, 5, 5)
    expect(ownership).toEqual({
      keying: 'sector',
      sectorIndex: 1,
      planetId: 44,
    })
  })

  it('builds a sector menu ownership target from the overlay id', () => {
    expect(resolveOwnershipAssertTargetForSector(sector)).toEqual({
      keying: 'sector',
      sectorIndex: 1,
    })
  })

  it('falls back to planet-keyed ownership when sectors are absent', () => {
    const ownership = resolveOwnershipAssertTargetForPlanet([], 9, 1, 1)
    expect(ownership).not.toBeNull()
    if (ownership == null) return
    expect(ownership).toEqual({ keying: 'planet', planetId: 9 })
    const body = {
      axis: 'ownership' as const,
      action: 'upsert' as const,
      ownerSlot: 2,
      planetId: ownership.keying === 'planet' ? ownership.planetId : null,
      sectorIndex: ownership.keying === 'sector' ? ownership.sectorIndex : null,
    }
    expect(body).toEqual({
      axis: 'ownership',
      action: 'upsert',
      ownerSlot: 2,
      planetId: 9,
      sectorIndex: null,
    })
  })
})

describe('isEventInsideHomeworldMenu', () => {
  it('returns false when the menu is not mounted', () => {
    expect(isEventInsideHomeworldMenu(document.createElement('div'), null)).toBe(false)
  })

  it('returns true for the menu element and its children', () => {
    const menu = document.createElement('div')
    const child = document.createElement('button')
    menu.appendChild(child)
    expect(isEventInsideHomeworldMenu(menu, menu)).toBe(true)
    expect(isEventInsideHomeworldMenu(child, menu)).toBe(true)
  })

  it('returns false for outside targets', () => {
    const menu = document.createElement('div')
    const outside = document.createElement('div')
    expect(isEventInsideHomeworldMenu(outside, menu)).toBe(false)
  })
})
