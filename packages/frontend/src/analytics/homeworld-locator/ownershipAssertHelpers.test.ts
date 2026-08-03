import { describe, expect, it } from 'vitest'
import { formatHomeworldOwnershipPickLabel } from './ownershipPickLabel'
import {
  homeworldSectorsPresentOnMap,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'
import {
  resolveOwnershipAssertTargetForPlanet,
  resolveOwnershipAssertTargetForSector,
} from './resolveOwnershipAssertTarget'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'

function sectorOverlay(index: number): MapRegionOverlay {
  return {
    kind: 'homeworld-sector',
    id: `homeworld-sector-${index}`,
    fillColor: '#f97316',
    fillOpacity: 0,
    geometry: {
      type: 'boundary',
      // Unit square covering (0.25,0.25) for hit-tests.
      vertices: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
        { x: 1, y: 1 },
        { x: 0, y: 1 },
      ],
      edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }, { type: 'line' }],
    },
  }
}

describe('formatHomeworldOwnershipPickLabel', () => {
  it('formats name (race) for the ownership pick-list', () => {
    expect(formatHomeworldOwnershipPickLabel('alice', 'The Federation')).toBe(
      'alice (The Federation)'
    )
  })

  it('omits race parentheses when race is missing', () => {
    expect(formatHomeworldOwnershipPickLabel('bob', null)).toBe('bob')
  })
})

describe('parseHomeworldSectorIndex', () => {
  it('parses homeworld-sector-{n} ids', () => {
    expect(parseHomeworldSectorIndex('homeworld-sector-3')).toBe(3)
    expect(parseHomeworldSectorIndex('ship-scan-1')).toBeNull()
  })

  it('detects sector overlays on the map', () => {
    expect(homeworldSectorsPresentOnMap([sectorOverlay(0)])).toBe(true)
    expect(homeworldSectorsPresentOnMap([{ kind: 'ship-scan' }])).toBe(false)
  })
})

describe('resolveOwnershipAssertTarget', () => {
  it('uses planet keying when no sector overlays exist', () => {
    expect(resolveOwnershipAssertTargetForPlanet([], 12, 0.5, 0.5)).toEqual({
      keying: 'planet',
      planetId: 12,
    })
  })

  it('resolves sector keying from a containing overlay', () => {
    expect(
      resolveOwnershipAssertTargetForPlanet([sectorOverlay(2)], 12, 0.5, 0.5)
    ).toEqual({
      keying: 'sector',
      sectorIndex: 2,
      planetId: 12,
    })
  })

  it('returns null when sectors exist but the planet is outside all of them', () => {
    expect(
      resolveOwnershipAssertTargetForPlanet([sectorOverlay(0)], 12, 50, 50)
    ).toBeNull()
  })

  it('resolves sector targets from overlay context menus', () => {
    expect(resolveOwnershipAssertTargetForSector(sectorOverlay(4))).toEqual({
      keying: 'sector',
      sectorIndex: 4,
    })
  })
})
