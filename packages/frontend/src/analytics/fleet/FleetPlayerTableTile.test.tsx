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
  it('shows provenance summary text while materializing', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[]}
        streamSlice={provenanceStreamSlice}
      />
    )

    const tile = screen.getByRole('region', { name: 'Alice fleet table' })
    expect(within(tile).getByRole('status')).toHaveTextContent('Collecting turn evidence')
  })

  it('shows spinner alongside partial rows while materializing', () => {
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
          summary: 'Refining fleet records',
          error: null,
        }}
      />
    )

    const tile = screen.getByRole('region', { name: 'Alice fleet table' })
    expect(within(tile).getByText('<= 318')).toBeInTheDocument()
    expect(within(tile).getByRole('status')).toHaveTextContent('Refining fleet records')
    expect(screen.queryByText('Waiting for fleet records.')).not.toBeInTheDocument()
  })
})
