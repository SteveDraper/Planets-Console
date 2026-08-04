import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { formatHomeworldSectorHoverLine } from './formatHomeworldSectorHover'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'

function sector(overrides: Partial<MapRegionOverlay> = {}): MapRegionOverlay {
  return {
    kind: HOMEWORLD_SECTOR_KIND,
    id: 'homeworld-sector-0',
    fillColor: '#f97316',
    fillOpacity: 0,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: 200, y: 0 },
        { x: 0, y: 200 },
        { x: 0, y: 100 },
        { x: 100, y: 0 },
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

describe('formatHomeworldSectorHoverLine', () => {
  it('formats pinned player identity with candidate count', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          isPinned: true,
          playerLabel: 'koshling (The Lizard Alliance)',
          candidateCount: 1,
        })
      )
    ).toBe('player: koshling (The Lizard Alliance) · definite · 1 candidate homeworld')
  })

  it('formats incomplete scan and plural candidates', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({ status: 'incomplete', candidateCount: 2 })
      )
    ).toBe('incomplete scan · 2 candidate homeworlds')
  })

  it('formats error as no candidates', () => {
    expect(
      formatHomeworldSectorHoverLine(sector({ status: 'error', candidateCount: 0 }))
    ).toBe('no candidates')
  })

  it('uses player known when pinned without label', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({ isPinned: true, candidateCount: 1, playerLabel: undefined })
      )
    ).toBe('player known · definite · 1 candidate homeworld')
  })

  it('formats unique ownership evidence owner', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          candidateCount: 2,
          possibleOwners: [
            {
              ownerSlot: 3,
              provenanceKinds: ['ship_travel_envelope'],
              playerLabel: 'alice (The Federation)',
              provenanceKindCounts: {
                ship_travel_envelope: 2,
                nearby_planet_ownership: 0,
              },
            },
          ],
        })
      )
    ).toBe(
      'homeworld owner: alice (The Federation) · ' +
        'definite (ship observations: 2, planet observations: 0) · ' +
        '2 candidate homeworlds'
    )
  })

  it('formats ambiguous ownership evidence owners', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          candidateCount: 3,
          possibleOwners: [
            {
              ownerSlot: 2,
              provenanceKinds: ['nearby_planet_ownership'],
              provenanceKindCounts: { nearby_planet_ownership: 1 },
            },
            {
              ownerSlot: 5,
              provenanceKinds: ['preferred_candidate_ownership'],
              playerLabel: 'bob (The Rebel Confederation)',
              provenanceKindCounts: { preferred_candidate_ownership: 1 },
            },
          ],
        })
      )
    ).toBe(
      'ambiguous · homeworld owners: slot 2 · ' +
        'inferred (ship observations: 0, planet observations: 1), ' +
        'bob (The Rebel Confederation) · ' +
        'inferred (ship observations: 0, planet observations: 1) · ' +
        '3 candidate homeworlds'
    )
  })

  it('ignores sector ownershipWinningStrength for ambiguous contenders', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          candidateCount: 2,
          ownershipWinningStrength: 'strong',
          possibleOwners: [
            {
              ownerSlot: 2,
              provenanceKinds: ['nearby_planet_ownership'],
              provenanceKindCounts: { nearby_planet_ownership: 1 },
            },
            {
              ownerSlot: 5,
              provenanceKinds: ['preferred_candidate_ownership'],
              playerLabel: 'bob (The Rebel Confederation)',
              provenanceKindCounts: { preferred_candidate_ownership: 1 },
            },
          ],
        })
      )
    ).toBe(
      'ambiguous · homeworld owners: slot 2 · ' +
        'inferred (ship observations: 0, planet observations: 1), ' +
        'bob (The Rebel Confederation) · ' +
        'inferred (ship observations: 0, planet observations: 1) · ' +
        '2 candidate homeworlds'
    )
  })

  it('applies ownershipWinningStrength for a unique owner', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          candidateCount: 1,
          ownershipWinningStrength: 'strong',
          possibleOwners: [
            {
              ownerSlot: 3,
              provenanceKinds: ['preferred_candidate_ownership'],
              playerLabel: 'alice (The Federation)',
              provenanceKindCounts: { preferred_candidate_ownership: 1 },
            },
          ],
        })
      )
    ).toBe(
      'homeworld owner: alice (The Federation) · ' +
        'definite (ship observations: 0, planet observations: 1) · ' +
        '1 candidate homeworld'
    )
  })

  it('keeps pinned player identity and appends ownership inference counts', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          isPinned: true,
          playerLabel: 'koshling (The Lizard Alliance)',
          candidateCount: 1,
          possibleOwners: [
            {
              ownerSlot: 1,
              provenanceKinds: ['ship_travel_envelope'],
              playerLabel: 'koshling (The Lizard Alliance)',
              provenanceKindCounts: {
                ship_travel_envelope: 2,
                nearby_planet_ownership: 0,
              },
            },
          ],
        })
      )
    ).toBe(
      'player: koshling (The Lizard Alliance) · ' +
        'definite (ship observations: 2, planet observations: 0) · ' +
        '1 candidate homeworld'
    )
  })

  it('labels pinned sectors without ownership evidence as definite', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          isPinned: true,
          playerLabel: 'koshling (The Lizard Alliance)',
          candidateCount: 1,
        })
      )
    ).toBe('player: koshling (The Lizard Alliance) · definite · 1 candidate homeworld')
  })

  it('returns null for non-homeworld kinds', () => {
    expect(
      formatHomeworldSectorHoverLine(sector({ kind: 'visibility-ship-scan' }))
    ).toBeNull()
  })
})
