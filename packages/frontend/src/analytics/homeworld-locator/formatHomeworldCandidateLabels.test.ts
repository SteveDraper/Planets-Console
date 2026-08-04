import { describe, expect, it } from 'vitest'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import {
  formatHomeworldCandidateConfidenceLabel,
  formatHomeworldCandidateOwnerSlotLabel,
} from './formatHomeworldCandidateLabels'
import type { HomeworldCandidateRecord } from './wireSchema'

function candidate(
  overrides: Partial<HomeworldCandidateRecord> = {}
): HomeworldCandidateRecord {
  return {
    planetId: overrides.planetId ?? 1,
    perspective: 'perspective' in overrides ? overrides.perspective! : 1,
    confidenceTier: overrides.confidenceTier ?? 'definite',
    attribution: overrides.attribution ?? 'inferred',
    assertedCue: overrides.assertedCue ?? false,
    locationAsserted: overrides.locationAsserted ?? false,
    isMostProbable: overrides.isMostProbable ?? false,
  }
}

describe('formatHomeworldCandidateConfidenceLabel', () => {
  it('uses Title Case by default and folds asserted into table labels', () => {
    expect(formatHomeworldCandidateConfidenceLabel(candidate())).toBe('Definite')
    expect(
      formatHomeworldCandidateConfidenceLabel(
        candidate({ confidenceTier: 'possible', isMostProbable: true })
      )
    ).toBe('Possible (most probable)')
    expect(
      formatHomeworldCandidateConfidenceLabel(candidate({ confidenceTier: 'possible' }))
    ).toBe('Possible')
    expect(
      formatHomeworldCandidateConfidenceLabel(
        candidate({ confidenceTier: 'definite', assertedCue: true }),
        { includeAsserted: true }
      )
    ).toBe('Definite (asserted)')
    expect(
      formatHomeworldCandidateConfidenceLabel(
        candidate({ confidenceTier: 'possible', isMostProbable: true, assertedCue: true }),
        { includeAsserted: true }
      )
    ).toBe('Possible (most probable, asserted)')
  })

  it('uses lowercase for hover without folding asserted', () => {
    expect(
      formatHomeworldCandidateConfidenceLabel(candidate(), { casing: 'lower' })
    ).toBe('definite')
    expect(
      formatHomeworldCandidateConfidenceLabel(
        candidate({ confidenceTier: 'possible', isMostProbable: true, assertedCue: true }),
        { casing: 'lower' }
      )
    ).toBe('possible (most probable)')
  })
})

describe('formatHomeworldCandidateOwnerSlotLabel', () => {
  const roster = [
    perspectiveRow(1, 'alice', { raceName: 'The Federation' }),
    perspectiveRow(2, 'bob', { raceName: 'The Lizards' }),
  ]

  it('uses Title Case orphan and slot fallbacks by default', () => {
    expect(formatHomeworldCandidateOwnerSlotLabel(null, roster)).toBe('Orphan')
    expect(formatHomeworldCandidateOwnerSlotLabel(3, roster)).toBe('Slot 3')
    expect(formatHomeworldCandidateOwnerSlotLabel(2, roster)).toBe('bob (The Lizards)')
  })

  it('uses lowercase orphan and slot fallbacks for hover', () => {
    expect(
      formatHomeworldCandidateOwnerSlotLabel(null, roster, { casing: 'lower' })
    ).toBe('orphan')
    expect(
      formatHomeworldCandidateOwnerSlotLabel(3, roster, { casing: 'lower' })
    ).toBe('slot 3')
  })
})
