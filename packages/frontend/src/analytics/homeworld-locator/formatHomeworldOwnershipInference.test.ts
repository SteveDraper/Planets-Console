import { describe, expect, it } from 'vitest'
import type { MapRegionPossibleOwner } from '../../api/mapRegionOverlayTypes'
import {
  formatHomeworldOwnershipInferenceSummary,
  resolveOwnershipEvidenceForCandidate,
} from './formatHomeworldOwnershipInference'

describe('formatHomeworldOwnershipInferenceSummary', () => {
  it('returns null when evidence is missing or empty', () => {
    expect(formatHomeworldOwnershipInferenceSummary(null)).toBeNull()
    expect(formatHomeworldOwnershipInferenceSummary(undefined)).toBeNull()
    expect(
      formatHomeworldOwnershipInferenceSummary({ provenanceKinds: [] })
    ).toBeNull()
  })

  it('expands inferred with ship and planet observation counts', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary({
        provenanceKinds: ['nearby_planet_ownership', 'ship_travel_envelope'],
        provenanceKindCounts: {
          ship_travel_envelope: 2,
          nearby_planet_ownership: 0,
        },
      })
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

  it('counts preferred-candidate ownership as planet observations', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary({
        provenanceKinds: ['preferred_candidate_ownership'],
        provenanceKindCounts: { preferred_candidate_ownership: 1 },
      })
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

  it('falls back to presence counts when kind counts are omitted', () => {
    expect(
      formatHomeworldOwnershipInferenceSummary({
        provenanceKinds: ['ship_travel_envelope'],
      })
    ).toBe('definite (ship observations: 1, planet observations: 0)')
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
