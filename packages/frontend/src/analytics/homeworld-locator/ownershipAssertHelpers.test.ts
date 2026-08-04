import { describe, expect, it } from 'vitest'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { buildPlanetOwnershipTargets } from './buildPlanetOwnershipTargets'
import { formatHomeworldOwnershipPickLabel } from './ownershipPickLabel'
import { buildOwnershipAssertionBody } from './ownershipAssertionBody'
import {
  homeworldSectorsPresentOnMap,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'
import {
  collectAssertedOwnerSlots,
  findHomeworldSectorOverlayByIndex,
  resolveOwnershipAssertedSlots,
  resolveOwnershipAssertTargetForPlanet,
  resolveOwnershipAssertTargetForSector,
  resolveOwnershipMenuSelectedSlots,
  resolveOwnershipRevokeSlots,
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

describe('resolveOwnershipRevokeSlots', () => {
  it('collects asserted owner slots from sector overlays', () => {
    const overlay = {
      ...sectorOverlay(1),
      possibleOwners: [
        { ownerSlot: 1, provenanceKinds: ['asserted'] },
        { ownerSlot: 2, provenanceKinds: ['ship_travel_envelope'] },
      ],
    }
    expect(collectAssertedOwnerSlots(overlay)).toEqual([1])
    expect(findHomeworldSectorOverlayByIndex([overlay], 1)?.id).toBe('homeworld-sector-1')
    expect(
      resolveOwnershipRevokeSlots([overlay], { keying: 'sector', sectorIndex: 1 })
    ).toEqual([1])
  })

  it('prefers bound owner slot for planet menus', () => {
    expect(
      resolveOwnershipRevokeSlots(
        [],
        { keying: 'planet', planetId: 12 },
        { boundOwnerSlot: 3 }
      )
    ).toEqual([3])
  })
})

describe('resolveOwnershipAssertedSlots', () => {
  it('returns asserted slots for sector targets', () => {
    const overlay = {
      ...sectorOverlay(1),
      possibleOwners: [
        { ownerSlot: 2, provenanceKinds: ['asserted'] },
        { ownerSlot: 3, provenanceKinds: ['nearby_planet_ownership'] },
      ],
    }
    expect(
      resolveOwnershipAssertedSlots([overlay], { keying: 'sector', sectorIndex: 1 })
    ).toEqual([2])
  })

  it('returns empty for planet-keyed targets', () => {
    expect(
      resolveOwnershipAssertedSlots([], { keying: 'planet', planetId: 12 })
    ).toEqual([])
  })
})

describe('resolveOwnershipMenuSelectedSlots', () => {
  it('prefers asserted slots over inferred possibles', () => {
    const overlay = {
      ...sectorOverlay(1),
      possibleOwners: [
        { ownerSlot: 2, provenanceKinds: ['asserted'] },
        { ownerSlot: 3, provenanceKinds: ['nearby_planet_ownership'] },
      ],
    }
    expect(
      resolveOwnershipMenuSelectedSlots([overlay], { keying: 'sector', sectorIndex: 1 })
    ).toEqual([2])
  })

  it('uses a single inferred sector owner when none are asserted', () => {
    const overlay = {
      ...sectorOverlay(1),
      possibleOwners: [{ ownerSlot: 4, provenanceKinds: ['ship_travel_envelope'] }],
    }
    expect(
      resolveOwnershipMenuSelectedSlots([overlay], { keying: 'sector', sectorIndex: 1 })
    ).toEqual([4])
  })

  it('stays Unknown when multiple inferred owners and no assert', () => {
    const overlay = {
      ...sectorOverlay(1),
      possibleOwners: [
        { ownerSlot: 1, provenanceKinds: ['nearby_planet_ownership'] },
        { ownerSlot: 2, provenanceKinds: ['ship_travel_envelope'] },
      ],
    }
    expect(
      resolveOwnershipMenuSelectedSlots([overlay], { keying: 'sector', sectorIndex: 1 })
    ).toEqual([])
  })

  it('uses candidate bound owner when planet-keyed and nothing asserted', () => {
    expect(
      resolveOwnershipMenuSelectedSlots([], { keying: 'planet', planetId: 12 }, {
        boundOwnerSlot: 3,
      })
    ).toEqual([3])
  })

  it('uses candidate bound owner when sector has no unique inferred owner', () => {
    expect(
      resolveOwnershipMenuSelectedSlots(
        [sectorOverlay(1)],
        { keying: 'sector', sectorIndex: 1, planetId: 12 },
        { boundOwnerSlot: 5 }
      )
    ).toEqual([5])
  })
})

describe('buildOwnershipAssertionBody', () => {
  it('builds planet-keyed upsert bodies', () => {
    expect(
      buildOwnershipAssertionBody('upsert', 2, { keying: 'planet', planetId: 9 })
    ).toEqual({
      axis: 'ownership',
      action: 'upsert',
      ownerSlot: 2,
      planetId: 9,
      sectorIndex: null,
    })
  })

  it('builds sector-keyed upsert bodies with optional planet id', () => {
    expect(
      buildOwnershipAssertionBody('upsert', 2, {
        keying: 'sector',
        sectorIndex: 1,
        planetId: 44,
      })
    ).toEqual({
      axis: 'ownership',
      action: 'upsert',
      ownerSlot: 2,
      planetId: 44,
      sectorIndex: 1,
    })
  })

  it('uses perspective ordinal as ownerSlot when host playerId differs', () => {
    const player = perspectiveRow(2, 'bob', { playerId: 847 })
    const body = buildOwnershipAssertionBody('upsert', player.ordinal, {
      keying: 'sector',
      sectorIndex: 1,
      planetId: 44,
    })
    expect(body.ownerSlot).toBe(2)
    expect(body.ownerSlot).not.toBe(player.playerId)
  })
})

describe('buildPlanetOwnershipTargets', () => {
  it('maps planets inside sectors to sector-keyed targets', () => {
    const overlays = [sectorOverlay(2)]
    const positions = new Map([[12, { x: 0.5, y: 0.5 }]])
    const targets = buildPlanetOwnershipTargets(overlays, positions)
    expect(targets.get(12)).toEqual({
      keying: 'sector',
      sectorIndex: 2,
      planetId: 12,
    })
  })
})
