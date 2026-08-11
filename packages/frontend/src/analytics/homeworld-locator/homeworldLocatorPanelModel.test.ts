/**
 * Unit tests for homeworld sector accordion panel model helpers.
 */

import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import {
  HOMEWORLD_PLANET_ENVELOPE_KIND,
  HOMEWORLD_SECTOR_KIND,
  parseHomeworldPlanetEnvelopePlanetId,
} from './homeworldSectorIndex'
import {
  buildHomeworldSectorPanelModel,
  clockwiseFromNorthSortKey,
  homeworldSectorAccordionTitle,
  planetIdsFromHomeworldPlanetEnvelopes,
  sectorMidAngleRadians,
  sortCandidatesPreferredFirst,
  sortHomeworldSectorsNorthernmostClockwise,
  sortRosterByPlayerIdAscending,
} from './homeworldLocatorPanelModel'
import type { HomeworldCandidateRecord } from './wireSchema'

/** Annular quarter-sector at origin spanning [angleStart, angleEnd] (CCW). */
function annularSector(
  id: string,
  angleStart: number,
  angleEnd: number,
  overrides: Partial<MapRegionOverlay> = {}
): MapRegionOverlay {
  const rOuter = 200
  const rInner = 100
  return {
    kind: HOMEWORLD_SECTOR_KIND,
    id,
    fillColor: '#f97316',
    fillOpacity: 0,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: rOuter * Math.cos(angleStart), y: rOuter * Math.sin(angleStart) },
        { x: rOuter * Math.cos(angleEnd), y: rOuter * Math.sin(angleEnd) },
        { x: rInner * Math.cos(angleEnd), y: rInner * Math.sin(angleEnd) },
        { x: rInner * Math.cos(angleStart), y: rInner * Math.sin(angleStart) },
      ],
      edges: [
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
        { type: 'line' },
        { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
        { type: 'line' },
      ],
    },
    isPinned: false,
    status: 'ok',
    candidateCount: 0,
    ...overrides,
  }
}

function candidate(
  overrides: Partial<HomeworldCandidateRecord> & Pick<HomeworldCandidateRecord, 'planetId'>
): HomeworldCandidateRecord {
  return {
    planetId: overrides.planetId,
    perspective: 'perspective' in overrides ? overrides.perspective! : 1,
    confidenceTier: overrides.confidenceTier ?? 'possible',
    attribution: overrides.attribution ?? 'inferred',
    assertedCue: overrides.assertedCue ?? false,
    locationAsserted: overrides.locationAsserted ?? false,
    isMostProbable: overrides.isMostProbable ?? false,
  }
}

/** Minimal planet-envelope overlay (geometry unused by player-tile membership). */
function planetEnvelope(planetId: number): MapRegionOverlay {
  return {
    kind: HOMEWORLD_PLANET_ENVELOPE_KIND,
    id: `homeworld-planet-envelope-${planetId}`,
    fillColor: '#f97316',
    fillOpacity: 0,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: 81, y: 0 },
        { x: 0, y: 81 },
        { x: -81, y: 0 },
        { x: 0, y: -81 },
      ],
      edges: [
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
      ],
    },
    isPinned: true,
    status: 'ok',
    candidateCount: 1,
  }
}

describe('homeworldLocatorPanelModel', () => {
  it('computes mid-angle from outer arc endpoints', () => {
    // North-east quarter: 0 → π/2, mid = π/4
    const overlay = annularSector('homeworld-sector-0', 0, Math.PI / 2)
    const mid = sectorMidAngleRadians(overlay)
    expect(mid).not.toBeNull()
    expect(mid!).toBeCloseTo(Math.PI / 4, 5)
  })

  it('sorts sectors northernmost then clockwise', () => {
    // Four equal sectors: mid-angles at 0 (east), π/2 (north), π (west), -π/2 (south)
    const east = annularSector('homeworld-sector-0', -Math.PI / 4, Math.PI / 4)
    const north = annularSector('homeworld-sector-1', Math.PI / 4, (3 * Math.PI) / 4)
    const west = annularSector('homeworld-sector-2', (3 * Math.PI) / 4, (5 * Math.PI) / 4)
    const south = annularSector('homeworld-sector-3', (5 * Math.PI) / 4, (7 * Math.PI) / 4)

    const ordered = sortHomeworldSectorsNorthernmostClockwise([east, south, west, north])
    expect(ordered.map((o) => o.id)).toEqual([
      'homeworld-sector-1', // north
      'homeworld-sector-0', // east (clockwise from north)
      'homeworld-sector-3', // south
      'homeworld-sector-2', // west
    ])
  })

  it('places northernmost first in clockwise-from-north keys', () => {
    expect(clockwiseFromNorthSortKey(Math.PI / 2)).toBeCloseTo(0, 5)
    expect(clockwiseFromNorthSortKey(0)).toBeCloseTo(Math.PI / 2, 5)
  })

  it('titles sectors from playerLabel, unique owner, or Unknown', () => {
    expect(
      homeworldSectorAccordionTitle(
        annularSector('homeworld-sector-0', 0, Math.PI / 2, {
          playerLabel: 'alice (The Federation)',
        })
      )
    ).toBe('alice (The Federation)')

    expect(
      homeworldSectorAccordionTitle(
        annularSector('homeworld-sector-1', 0, Math.PI / 2, {
          possibleOwners: [
            {
              ownerSlot: 2,
              provenanceKinds: ['ship_travel_envelope'],
              playerLabel: 'bob (The Lizards)',
            },
          ],
        })
      )
    ).toBe('bob (The Lizards)')

    expect(
      homeworldSectorAccordionTitle(
        annularSector('homeworld-sector-2', 0, Math.PI / 2, {
          playerLabel: 'enlar (The Privateer Bands)',
          possibleOwners: [
            { ownerSlot: 1, provenanceKinds: ['nearby_planet_ownership'] },
            { ownerSlot: 3, provenanceKinds: ['ship_travel_envelope'] },
          ],
        })
      )
    ).toBe('Unknown')
  })

  it('orders candidates preferred-first', () => {
    const rows = [
      candidate({ planetId: 30, confidenceTier: 'possible', isMostProbable: false }),
      candidate({ planetId: 10, confidenceTier: 'definite' }),
      candidate({ planetId: 20, confidenceTier: 'possible', isMostProbable: true }),
      candidate({ planetId: 11, confidenceTier: 'definite' }),
    ]
    expect(sortCandidatesPreferredFirst(rows).map((r) => r.planetId)).toEqual([
      10, 11, 20, 30,
    ])
  })

  it('builds player model from Core planet-envelope overlays', () => {
    const roster = [
      perspectiveRow(2, 'bob', { playerId: 847, raceName: 'The Lizards' }),
      perspectiveRow(1, 'alice', { playerId: 2, raceName: 'The Federation' }),
    ]
    const rows = [
      candidate({ planetId: 30, perspective: 1, confidenceTier: 'possible' }),
      candidate({ planetId: 10, perspective: 1, confidenceTier: 'definite' }),
      candidate({
        planetId: 20,
        perspective: 2,
        confidenceTier: 'possible',
        locationAsserted: true,
      }),
      candidate({ planetId: 99, perspective: null, confidenceTier: 'possible' }),
      candidate({
        planetId: 40,
        perspective: 2,
        confidenceTier: 'possible',
        isMostProbable: true,
      }),
    ]
    // Core emits envelopes only for sidebar-qualifying planets (10, 20).
    const envelopes = [planetEnvelope(10), planetEnvelope(20)]
    const model = buildHomeworldSectorPanelModel(rows, envelopes, new Map(), roster)
    expect(model.kind).toBe('players')
    if (model.kind !== 'players') return
    // playerId ascending: alice (2) then bob (847)
    expect(model.sections.map((s) => s.playerId)).toEqual([2, 847])
    expect(model.sections.map((s) => s.title)).toEqual([
      'alice (The Federation)',
      'bob (The Lizards)',
    ])
    expect(model.sections[0]!.candidates.map((c) => c.planetId)).toEqual([10])
    expect(model.sections[1]!.candidates.map((c) => c.planetId)).toEqual([20])
  })

  it('excludes candidates whose planet lacks a Core envelope overlay', () => {
    const roster = [perspectiveRow(1, 'alice', { playerId: 2 })]
    const rows = [
      candidate({ planetId: 10, perspective: 1, confidenceTier: 'definite' }),
      candidate({
        planetId: 20,
        perspective: 1,
        confidenceTier: 'possible',
        locationAsserted: true,
      }),
    ]
    // Envelope only for 10 -- FE must not re-apply Core qualifying policy.
    const model = buildHomeworldSectorPanelModel(
      rows,
      [planetEnvelope(10)],
      new Map(),
      roster
    )
    expect(model.kind).toBe('players')
    if (model.kind !== 'players') return
    expect(model.sections[0]!.candidates.map((c) => c.planetId)).toEqual([10])
  })

  it('binds envelope planets only to matching perspective ordinal', () => {
    const roster = [
      perspectiveRow(1, 'alice', { playerId: 2 }),
      perspectiveRow(2, 'bob', { playerId: 3 }),
    ]
    const rows = [
      candidate({ planetId: 10, perspective: 1, confidenceTier: 'definite' }),
      candidate({ planetId: 10, perspective: 2, confidenceTier: 'definite' }),
    ]
    const model = buildHomeworldSectorPanelModel(
      rows,
      [planetEnvelope(10)],
      new Map(),
      roster
    )
    expect(model.kind).toBe('players')
    if (model.kind !== 'players') return
    expect(model.sections[0]!.candidates.map((c) => c.planetId)).toEqual([10])
    expect(model.sections[1]!.candidates.map((c) => c.planetId)).toEqual([10])
  })

  it('parses planet ids from homeworld-planet-envelope overlay ids', () => {
    expect(parseHomeworldPlanetEnvelopePlanetId('homeworld-planet-envelope-7')).toBe(7)
    expect(parseHomeworldPlanetEnvelopePlanetId('homeworld-sector-3')).toBeNull()
    expect(parseHomeworldPlanetEnvelopePlanetId('homeworld-planet-envelope-x')).toBeNull()
    expect(
      [...planetIdsFromHomeworldPlanetEnvelopes([planetEnvelope(7), planetEnvelope(12)])].sort(
        (a, b) => a - b
      )
    ).toEqual([7, 12])
  })

  it('sorts roster by playerId ascending', () => {
    const roster = [
      perspectiveRow(1, 'alice', { playerId: 99 }),
      perspectiveRow(2, 'bob', { playerId: 3 }),
    ]
    expect(sortRosterByPlayerIdAscending(roster).map((p) => p.playerId)).toEqual([
      3, 99,
    ])
  })

  it('groups candidates into sectors by map position', () => {
    const north = annularSector('homeworld-sector-1', Math.PI / 4, (3 * Math.PI) / 4, {
      playerLabel: 'north-owner',
      candidateCount: 1,
    })
    const east = annularSector('homeworld-sector-0', -Math.PI / 4, Math.PI / 4, {
      candidateCount: 1,
    })
    const rows = [
      candidate({ planetId: 100, confidenceTier: 'possible', isMostProbable: true }),
      candidate({ planetId: 101, confidenceTier: 'definite' }),
    ]
    const positions = new Map([
      [100, { x: 150, y: 0 }], // east
      [101, { x: 0, y: 150 }], // north
    ])
    const model = buildHomeworldSectorPanelModel(rows, [east, north], positions, [])
    expect(model.kind).toBe('sectors')
    if (model.kind === 'sectors') {
      expect(model.sections.map((s) => s.title)).toEqual(['north-owner', 'Unknown'])
      expect(model.sections[0]!.candidates.map((c) => c.planetId)).toEqual([101])
      expect(model.sections[1]!.candidates.map((c) => c.planetId)).toEqual([100])
      expect(model.unassigned).toEqual([])
    }
  })
})
