import { describe, expect, it } from 'vitest'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { isEventInsideHomeworldMenu } from './HomeworldMapContextMenu'
import { applyHomeworldRegionDisplayMode } from './homeworldRegionDisplayMode'
import { buildOwnershipAssertionBody } from './ownershipAssertionBody'
import {
  collectAssertedOwnerSlots,
  resolveOwnershipAssertTargetForPlanet,
  resolveOwnershipAssertTargetForSector,
  resolveOwnershipRevokeSlots,
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
    expect(buildOwnershipAssertionBody('upsert', 2, ownership)).toEqual({
      axis: 'ownership',
      action: 'upsert',
      ownerSlot: 2,
      planetId: 9,
      sectorIndex: null,
    })
  })

  it('sector-keys from raw overlays when display mode off hides sectors from paint', () => {
    const paintOverlays = applyHomeworldRegionDisplayMode([sector], 'off')
    expect(paintOverlays).toHaveLength(0)
    expect(resolveOwnershipAssertTargetForPlanet(paintOverlays, 44, 5, 5)).toEqual({
      keying: 'planet',
      planetId: 44,
    })
    expect(resolveOwnershipAssertTargetForPlanet([sector], 44, 5, 5)).toEqual({
      keying: 'sector',
      sectorIndex: 1,
      planetId: 44,
    })
  })

  it('resolves ownership revoke slots from asserted sector owners', () => {
    const sectorWithAssertedOwner: MapRegionOverlay = {
      ...sector,
      possibleOwners: [
        {
          ownerSlot: 2,
          provenanceKinds: ['asserted'],
          playerLabel: 'bob (The Lizards)',
        },
        {
          ownerSlot: 3,
          provenanceKinds: ['nearby_planet_ownership'],
        },
      ],
    }
    const target = resolveOwnershipAssertTargetForSector(sectorWithAssertedOwner)
    expect(target).not.toBeNull()
    if (target == null) return
    expect(collectAssertedOwnerSlots(sectorWithAssertedOwner)).toEqual([2])
    expect(resolveOwnershipRevokeSlots([sectorWithAssertedOwner], target)).toEqual([2])
  })

  it('planet menu revoke mirrors panel bound owner slot', () => {
    const target = { keying: 'planet' as const, planetId: 9 }
    expect(
      resolveOwnershipRevokeSlots([], target, { boundOwnerSlot: 2 })
    ).toEqual([2])
    expect(buildOwnershipAssertionBody('revoke', 2, target)).toEqual({
      axis: 'ownership',
      action: 'revoke',
      ownerSlot: 2,
      planetId: 9,
      sectorIndex: null,
    })
  })

  it('map menu ownership upsert uses roster ordinal, not host playerId', () => {
    const player = perspectiveRow(2, 'bob', { playerId: 847 })
    const ownership = resolveOwnershipAssertTargetForPlanet([sector], 44, 5, 5)
    expect(ownership).not.toBeNull()
    if (ownership == null) return
    // HomeworldMapContextMenu roster buttons call runOwnership with player.ordinal.
    const body = buildOwnershipAssertionBody('upsert', player.ordinal, ownership)
    expect(body).toEqual({
      axis: 'ownership',
      action: 'upsert',
      ownerSlot: 2,
      planetId: 44,
      sectorIndex: 1,
    })
    expect(body.ownerSlot).not.toBe(player.playerId)
  })

  it('sector-keyed planet menu revoke uses bound owner, not all sector asserts', () => {
    const sectorWithAssertedOwner: MapRegionOverlay = {
      ...sector,
      possibleOwners: [
        { ownerSlot: 1, provenanceKinds: ['asserted'] },
        { ownerSlot: 2, provenanceKinds: ['asserted'] },
      ],
    }
    const target = resolveOwnershipAssertTargetForPlanet([sectorWithAssertedOwner], 44, 5, 5)
    expect(target).not.toBeNull()
    if (target == null) return
    expect(
      resolveOwnershipRevokeSlots([sectorWithAssertedOwner], target, { boundOwnerSlot: 2 })
    ).toEqual([2])
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
