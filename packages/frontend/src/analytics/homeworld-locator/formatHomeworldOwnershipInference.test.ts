import { describe, expect, it } from 'vitest'
import type { MapRegionPossibleOwner } from '../../api/mapRegionOverlayTypes'
import {
  formatHomeworldOwnershipInferenceSummary,
  resolveOwnershipEvidenceForCandidate,
  uniqueOwnershipWinningStrength,
} from './formatHomeworldOwnershipInference'

describe('uniqueOwnershipWinningStrength', () => {
  it('returns strength only for a unique owner set', () => {
    expect(uniqueOwnershipWinningStrength([{ ownerSlot: 1 }], 'strong')).toBe(
      'strong'
    )
    expect(
      uniqueOwnershipWinningStrength([{ ownerSlot: 1 }, { ownerSlot: 2 }], 'strong')
    ).toBeUndefined()
    expect(uniqueOwnershipWinningStrength([], 'strong')).toBeUndefined()
    expect(uniqueOwnershipWinningStrength(undefined, 'strong')).toBeUndefined()
  })
})

describe('formatHomeworldOwnershipInferenceSummary', () => {
  it('returns null when evidence is missing or empty', () => {
    expect(formatHomeworldOwnershipInferenceSummary(null)).toBeNull()
    expect(formatHomeworldOwnershipInferenceSummary(undefined)).toBeNull()
    expect(
      formatHomeworldOwnershipInferenceSummary({ provenanceKinds: [] })
    ).toBeNull()
  })

  it('expands ship and planet observation counts under winningStrength', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary(
        {
          provenanceKinds: ['nearby_planet_ownership', 'ship_travel_envelope'],
          provenanceKindCounts: {
            ship_travel_envelope: 2,
            nearby_planet_ownership: 0,
          },
        },
        { winningStrength: 'strong' }
      )
    ).toBe('definite (ship observations: 2, planet observations: 0)')
  })

  it('labels unique strong ownership as definite via winningStrength', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary(
        {
          provenanceKinds: ['preferred_candidate_ownership'],
          provenanceKindCounts: { preferred_candidate_ownership: 1 },
        },
        { winningStrength: 'strong' }
      )
    ).toBe('definite (ship observations: 0, planet observations: 1)')
  })

  it('labels weak winningStrength as inferred even when ship envelope is present', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary(
        {
          provenanceKinds: ['ship_travel_envelope', 'nearby_planet_ownership'],
          provenanceKindCounts: {
            ship_travel_envelope: 1,
            nearby_planet_ownership: 1,
          },
        },
        { winningStrength: 'weak' }
      )
    ).toBe('inferred (ship observations: 1, planet observations: 1)')
  })

  it('counts preferred-candidate ownership as planet observations', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary(
        {
          provenanceKinds: ['preferred_candidate_ownership'],
          provenanceKindCounts: { preferred_candidate_ownership: 1 },
        },
        { winningStrength: 'weak' }
      )
    ).toBe('inferred (ship observations: 0, planet observations: 1)')
  })

  it('labels asserted provenance as asserted', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary({
        provenanceKinds: ['asserted', 'ship_travel_envelope'],
        provenanceKindCounts: { asserted: 1, ship_travel_envelope: 2 },
      })
    ).toBe('asserted')
  })

  it('labels asserted via winningStrength without asserted kind', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary(
        {
          provenanceKinds: ['ship_travel_envelope'],
          provenanceKindCounts: { ship_travel_envelope: 1 },
        },
        { winningStrength: 'asserted' }
      )
    ).toBe('asserted')
  })

  it('falls back to presence counts when kind counts are omitted', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary(
        {
          provenanceKinds: ['ship_travel_envelope'],
        },
        { winningStrength: 'strong' }
      )
    ).toBe('definite (ship observations: 1, planet observations: 0)')
  })

  it('legacy: without winningStrength, ship envelope still labels definite', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary({
        provenanceKinds: ['ship_travel_envelope'],
      })
    ).toBe('definite (ship observations: 1, planet observations: 0)')
  })

  it('legacy: without winningStrength, planet-only evidence labels inferred', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary({
        provenanceKinds: ['preferred_candidate_ownership'],
        provenanceKindCounts: { preferred_candidate_ownership: 1 },
      })
    ).toBe('inferred (ship observations: 0, planet observations: 1)')
  })
})

describe('resolveOwnershipEvidenceForCandidate', () => {
  const owners: MapRegionPossibleOwner[] = [
    {
      ownerSlot: 1,
      provenanceKinds: ['nearby_planet_ownership'],
      provenanceKindCounts: { nearby_planet_ownership: 1 },
    },
    {
      ownerSlot: 3,
      provenanceKinds: ['ship_travel_envelope'],
      provenanceKindCounts: { ship_travel_envelope: 2 },
    },
  ]

  it('matches the candidate perspective slot', () => {
    expect(resolveOwnershipEvidenceForCandidate(owners, 3)?.ownerSlot).toBe(3)
  })

  it('uses the unique owner when perspective is unbound', () => {
    expect(
      resolveOwnershipEvidenceForCandidate([owners[1]!], null)?.ownerSlot
    ).toBe(3)
  })

  it('returns null when ambiguous and perspective does not match', () => {
    expect(resolveOwnershipEvidenceForCandidate(owners, null)).toBeNull()
    expect(resolveOwnershipEvidenceForCandidate(owners, 9)).toBeNull()
  })
})
