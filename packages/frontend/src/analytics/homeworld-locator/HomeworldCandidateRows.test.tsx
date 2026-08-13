import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { useMapAttentionRequestStore } from '../../stores/mapAttentionRequest'
import { selectHomeworldCandidateForMapAttention } from './homeworldCandidateAttention'
import { HomeworldCandidateRows } from './HomeworldCandidateRows'
import type { HomeworldCandidateRecord } from './wireSchema'

function candidateRow(
  overrides: Partial<HomeworldCandidateRecord> & Pick<HomeworldCandidateRecord, 'planetId'>
): HomeworldCandidateRecord {
  return {
    planetId: overrides.planetId,
    perspective: 'perspective' in overrides ? overrides.perspective! : 1,
    confidenceTier: overrides.confidenceTier ?? 'definite',
    attribution: overrides.attribution ?? 'inferred',
    assertedCue: overrides.assertedCue ?? false,
    locationAsserted: overrides.locationAsserted ?? false,
    isMostProbable: overrides.isMostProbable ?? false,
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
        roster={roster}
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
        roster={[perspectiveRow(1, 'alice')]}
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
        roster={[perspectiveRow(1, 'alice')]}
        onSelectPlanet={vi.fn()}
      />
    )

    expect(screen.getByText('Orphan')).toBeInTheDocument()
  })

  it('folds locationAsserted into the Confidence cell, not ownership-only assertedCue', () => {
    render(
      <HomeworldCandidateRows
        rows={[
          candidateRow({
            planetId: 1,
            confidenceTier: 'definite',
            assertedCue: true,
            locationAsserted: true,
          }),
          candidateRow({
            planetId: 2,
            confidenceTier: 'possible',
            isMostProbable: true,
            assertedCue: true,
            locationAsserted: true,
          }),
          candidateRow({
            planetId: 3,
            confidenceTier: 'possible',
            assertedCue: true,
            locationAsserted: false,
          }),
        ]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[perspectiveRow(1, 'alice')]}
        onSelectPlanet={vi.fn()}
      />
    )

    expect(screen.getByText('Definite (asserted)')).toBeInTheDocument()
    expect(screen.getByText('Possible (most probable, asserted)')).toBeInTheDocument()
    expect(screen.getByText('Possible')).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Asserted' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /assert hw/i })).not.toBeInTheDocument()
  })

  it('omits Owner column when showOwnerColumn is false', () => {
    render(
      <HomeworldCandidateRows
        rows={[candidateRow({ planetId: 12, perspective: 1 })]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[perspectiveRow(1, 'alice', { raceName: 'The Federation' })]}
        onSelectPlanet={vi.fn()}
        showOwnerColumn={false}
      />
    )

    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.queryByText('alice (The Federation)')).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Owner' })).not.toBeInTheDocument()
  })

  it('invokes onSelectPlanet when a candidate row is clicked', async () => {
    const user = userEvent.setup()
    const onSelectPlanet = vi.fn()
    render(
      <HomeworldCandidateRows
        rows={[candidateRow({ planetId: 55 })]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[perspectiveRow(1, 'alice')]}
        onSelectPlanet={onSelectPlanet}
      />
    )

    await user.click(screen.getByText('55'))
    expect(onSelectPlanet).toHaveBeenCalledWith(55)
  })

  it('wires row click through selectHomeworldCandidateForMapAttention', async () => {
    const user = userEvent.setup()
    useMapAttentionRequestStore.getState().clearAttention()

    render(
      <HomeworldCandidateRows
        rows={[candidateRow({ planetId: 55 })]}
        baselineDegraded={false}
        baselineTurn={null}
        roster={[perspectiveRow(1, 'alice')]}
        onSelectPlanet={selectHomeworldCandidateForMapAttention}
      />
    )

    await user.click(screen.getByText('55'))

    expect(useMapAttentionRequestStore.getState().pending).toMatchObject({
      kind: 'homeworld-planet',
      planetId: 55,
    })
  })
})
