import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import type { HomeworldCandidateRecord } from './wireSchema'

function candidateRow(
  overrides: Partial<HomeworldCandidateRecord> & Pick<HomeworldCandidateRecord, 'planetId'>
): HomeworldCandidateRecord {
  return {
    perspective: 1,
    confidenceTier: 'definite',
    attribution: 'inferred',
    assertedCue: false,
    isMostProbable: false,
    ...overrides,
  }
}

describe('HomeworldCandidateRows', () => {
  it('labels Owner by roster ordinal only when playerId collides with another slot', () => {
    // Slot 1's host playerId equals slot 2's ordinal. Dual-match (playerId || ordinal)
    // would mis-label perspective 2 as alice.
    const roster = [
      perspectiveRow(1, 'alice', { playerId: 2, raceName: 'The Federation' }),
      perspectiveRow(2, 'bob', { playerId: 847, raceName: 'The Lizards' }),
    ]

    render(
      <HomeworldCandidateRows
        rows={[candidateRow({ planetId: 12, perspective: 2 })]}
        baselineDegraded={false}
        baselineTurn={null}
        mode="readOnly"
        roster={roster}
        selectedPlanetId={null}
        onSelectPlanet={vi.fn()}
      />
    )

    expect(screen.getByText('bob (The Lizards)')).toBeInTheDocument()
    expect(screen.queryByText('alice (The Federation)')).not.toBeInTheDocument()
  })

  it('falls back to Slot N when ordinal is absent from roster', () => {
    render(
      <HomeworldCandidateRows
        rows={[candidateRow({ planetId: 9, perspective: 3 })]}
        baselineDegraded={false}
        baselineTurn={null}
        mode="readOnly"
        roster={[perspectiveRow(1, 'alice')]}
        selectedPlanetId={null}
        onSelectPlanet={vi.fn()}
      />
    )

    expect(screen.getByText('Slot 3')).toBeInTheDocument()
  })

  it('shows Orphan when perspective is null', () => {
    render(
      <HomeworldCandidateRows
        rows={[candidateRow({ planetId: 44, perspective: null })]}
        baselineDegraded={false}
        baselineTurn={null}
        mode="readOnly"
        roster={[perspectiveRow(1, 'alice')]}
        selectedPlanetId={null}
        onSelectPlanet={vi.fn()}
      />
    )

    expect(screen.getByText('Orphan')).toBeInTheDocument()
  })
})
