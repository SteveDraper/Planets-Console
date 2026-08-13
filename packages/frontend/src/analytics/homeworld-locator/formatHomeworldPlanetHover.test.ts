import { describe, expect, it } from 'vitest'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { formatHomeworldPlanetHover } from './formatHomeworldPlanetHover'
import type { HomeworldCandidateRecord } from './wireSchema'

function candidate(
  overrides: Partial<HomeworldCandidateRecord> = {}
): HomeworldCandidateRecord {
  return {
    planetId: overrides.planetId ?? 12,
    perspective: 'perspective' in overrides ? overrides.perspective! : 1,
    confidenceTier: overrides.confidenceTier ?? 'definite',
    attribution: overrides.attribution ?? 'inferred',
    assertedCue: overrides.assertedCue ?? false,
    locationAsserted: overrides.locationAsserted ?? false,
    isMostProbable: overrides.isMostProbable ?? false,
  }
}

describe('formatHomeworldPlanetHover', () => {
  it('formats definite asserted candidates with roster owner label', () => {
    expect(
      formatHomeworldPlanetHover(
        candidate({
          attribution: 'user_asserted',
          assertedCue: true,
          locationAsserted: true,
        }),
        [perspectiveRow(1, 'alice', { raceName: 'The Federation' })]
      )
    ).toBe(
      'planet 12 · definite · owner: alice (The Federation) · user_asserted · asserted'
    )
  })

  it('formats most-probable orphans without a roster match', () => {
    expect(
      formatHomeworldPlanetHover(
        candidate({
          planetId: 44,
          perspective: null,
          confidenceTier: 'possible',
          isMostProbable: true,
          attribution: 'inferred',
        })
      )
    ).toBe('planet 44 · possible (most probable) · owner: orphan · inferred')
  })

  it('does not treat ownership-only assertedCue as a homeworld location pin', () => {
    expect(
      formatHomeworldPlanetHover(
        candidate({
          planetId: 45,
          perspective: 2,
          confidenceTier: 'possible',
          isMostProbable: true,
          attribution: 'user_asserted',
          assertedCue: true,
          locationAsserted: false,
        }),
        [perspectiveRow(2, 'dead', { raceName: 'The Solar Federation' })],
        {
          ownershipWinningStrength: 'asserted',
          possibleOwners: [
            {
              ownerSlot: 2,
              provenanceKinds: ['asserted'],
              playerLabel: 'dead (The Solar Federation)',
              provenanceKindCounts: { asserted: 1 },
            },
          ],
        }
      )
    ).toBe(
      'planet 45 · possible (most probable) · owner: dead (The Solar Federation) · asserted'
    )
  })

  it('expands inferred ownership with observation counts from sector evidence', () => {
    expect(
      formatHomeworldPlanetHover(
        candidate({
          perspective: 3,
          confidenceTier: 'possible',
          attribution: 'inferred',
        }),
        [perspectiveRow(3, 'enlar', { raceName: 'The Privateers' })],
        {
          possibleOwners: [
            {
              ownerSlot: 3,
              provenanceKinds: ['ship_travel_envelope'],
              playerLabel: 'enlar (The Privateers)',
              provenanceKindCounts: {
                ship_travel_envelope: 2,
                nearby_planet_ownership: 0,
              },
            },
          ],
        }
      )
    ).toBe(
      'planet 12 · possible · owner: enlar (The Privateers) · ' +
        'definite (ship observations: 2, planet observations: 0)'
    )
  })

  it('ignores sector ownershipWinningStrength when possibleOwners are ambiguous', () => {
    expect(
      formatHomeworldPlanetHover(
        candidate({
          perspective: 3,
          confidenceTier: 'possible',
          attribution: 'inferred',
        }),
        [perspectiveRow(3, 'enlar', { raceName: 'The Privateers' })],
        {
          ownershipWinningStrength: 'strong',
          possibleOwners: [
            {
              ownerSlot: 3,
              provenanceKinds: ['preferred_candidate_ownership'],
              provenanceKindCounts: { preferred_candidate_ownership: 1 },
            },
            {
              ownerSlot: 5,
              provenanceKinds: ['nearby_planet_ownership'],
              provenanceKindCounts: { nearby_planet_ownership: 1 },
            },
          ],
        }
      )
    ).toBe(
      'planet 12 · possible · owner: enlar (The Privateers) · ' +
        'inferred (ship observations: 0, planet observations: 1)'
    )
  })

  it('does not label matched ship-envelope owner definite under ambiguous owners', () => {
    expect(
      formatHomeworldPlanetHover(
        candidate({
          perspective: 3,
          confidenceTier: 'possible',
          attribution: 'inferred',
        }),
        [perspectiveRow(3, 'enlar', { raceName: 'The Privateers' })],
        {
          possibleOwners: [
            {
              ownerSlot: 3,
              provenanceKinds: ['ship_travel_envelope'],
              provenanceKindCounts: { ship_travel_envelope: 2 },
            },
            {
              ownerSlot: 5,
              provenanceKinds: ['ship_travel_envelope'],
              provenanceKindCounts: { ship_travel_envelope: 1 },
            },
          ],
        }
      )
    ).toBe(
      'planet 12 · possible · owner: enlar (The Privateers) · ' +
        'inferred (ship observations: 2, planet observations: 0)'
    )
  })
})
