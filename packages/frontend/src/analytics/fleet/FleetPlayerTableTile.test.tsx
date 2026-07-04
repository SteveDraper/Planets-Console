import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'

const provenanceStreamSlice: FleetPlayerStreamSlice = {
  discrepancyOverlay: 'inherit',
  isComplete: false,
  isFinal: false,
  isPending: false,
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
})
