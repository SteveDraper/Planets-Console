import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetTableRecord } from './fleetTableWireSchema'

const activeRecord: FleetTableRecord = {
  recordId: 'rec-active',
  disposition: 'active',
  qualifiers: {},
  fields: {
    shipId: { kind: 'bounded', operator: 'lte', value: 318 },
    hull: { kind: 'known', value: 13 },
    engine: { kind: 'known', value: 9 },
    beams: { kind: 'options', values: [3, 5] },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'known', value: 4 },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [],
}

const provenanceStreamSlice: FleetPlayerStreamSlice = {
  discrepancyOverlay: 'inherit',
  isComplete: false,
  isFinal: false,
  isPending: true,
  summary: 'Collecting turn evidence',
  error: null,
}

describe('FleetPlayerTableTile provenance progress', () => {
  it('does not show the materialization spinner for earlier-turn provenance', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[]}
        streamSlice={provenanceStreamSlice}
      />
    )

    const tile = screen.getByRole('region', { name: 'Alice fleet table' })
    expect(within(tile).queryByText('Fleet materialization in progress')).not.toBeInTheDocument()
    expect(within(tile).queryByText('Collecting turn evidence')).not.toBeInTheDocument()
  })

  it('shows the materialization spinner alongside rows while this turn is written', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[activeRecord]}
        streamSlice={{
          records: [activeRecord],
          discrepancyOverlay: 'inherit',
          isComplete: false,
          isFinal: false,
          isPending: true,
          ledgerWriting: true,
          freshness: 'subject-to-revision',
          summary: 'Fleet materialization in progress',
          error: null,
        }}
      />
    )

    const tile = screen.getByRole('region', { name: 'Alice fleet table' })
    expect(within(tile).getByText('<= 318')).toBeInTheDocument()
    const label = within(tile).getByText('Provisional')
    expect(label).toHaveAttribute(
      'title',
      'This is a saved answer from before a newer result for this player. It may change once that result is included. Backfill earlier turns updates turns you are not viewing. Otherwise a turn updates when you open it.'
    )
    expect(label.className).toContain('ml-2')
    expect(label.className).toContain('font-normal')
    expect(label.className).toContain('text-amber-300')
    expect(within(tile).getByRole('status')).toHaveTextContent('Fleet materialization in progress')
    expect(screen.queryByText('Waiting for fleet records.')).not.toBeInTheDocument()
  })
})
