import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { formatHomeworldSectorHoverLine } from './formatHomeworldSectorHover'
import { HOMEWORLD_SECTOR_KIND } from './homeworldRegionDisplayMode'

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
    ).toBe('player: koshling (The Lizard Alliance) · 1 candidate homeworld')
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
    ).toBe('player known · 1 candidate homeworld')
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
            },
          ],
        })
      )
    ).toBe('homeworld owner: alice (The Federation) · 2 candidate homeworlds')
  })

  it('formats ambiguous ownership evidence owners', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          candidateCount: 3,
          possibleOwners: [
            { ownerSlot: 2, provenanceKinds: ['nearby_planet_ownership'] },
            {
              ownerSlot: 5,
              provenanceKinds: ['preferred_candidate_ownership'],
              playerLabel: 'bob (The Rebel Confederation)',
            },
          ],
        })
      )
    ).toBe(
      'ambiguous · homeworld owners: slot 2, bob (The Rebel Confederation) · 3 candidate homeworlds'
    )
  })

  it('prefers pinned player over possibleOwners to avoid duplicate owner text', () => {
    expect(
      formatHomeworldSectorHoverLine(
        sector({
          isPinned: true,
          playerLabel: 'koshling (The Lizard Alliance)',
          candidateCount: 1,
          possibleOwners: [
            {
              ownerSlot: 1,
              provenanceKinds: ['preferred_candidate_ownership'],
              playerLabel: 'koshling (The Lizard Alliance)',
            },
          ],
        })
      )
    ).toBe('player: koshling (The Lizard Alliance) · 1 candidate homeworld')
  })

  it('returns null for non-homeworld kinds', () => {
    expect(
      formatHomeworldSectorHoverLine(sector({ kind: 'visibility-ship-scan' }))
    ).toBeNull()
  })
})
