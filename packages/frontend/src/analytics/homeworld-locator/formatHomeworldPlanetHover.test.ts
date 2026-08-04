/**
 * Unit tests for thin FE planet hover summary.
 */

import { describe, expect, it } from 'vitest'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { formatHomeworldPlanetHover } from './formatHomeworldPlanetHover'
import type { HomeworldCandidateRecord } from './wireSchema'

function row(
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

describe('formatHomeworldPlanetHover', () => {
  it('summarizes definite asserted candidate with roster owner', () => {
    expect(
      formatHomeworldPlanetHover(
        row({
          planetId: 12,
          confidenceTier: 'definite',
          attribution: 'user_asserted',
          assertedCue: true,
          perspective: 1,
        }),
        [perspectiveRow(1, 'alice', { raceName: 'The Federation' })]
      )
    ).toBe(
      'planet 12 · definite · owner: alice (The Federation) · user_asserted · asserted'
    )
  })

  it('marks most-probable possibles and orphan owners', () => {
    expect(
      formatHomeworldPlanetHover(
        row({
          planetId: 44,
          perspective: null,
          isMostProbable: true,
          attribution: 'inferred',
        })
      )
    ).toBe('planet 44 · possible (most probable) · owner: orphan · inferred')
  })
})
