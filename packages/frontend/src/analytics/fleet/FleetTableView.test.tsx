import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import { FleetTableView } from './FleetTableView'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import type { FleetTableRecord, FleetTableWire } from './fleetTableWireSchema'

const activeRecord: FleetTableRecord = {
  recordId: 'rec-active',
  disposition: 'active',
  qualifiers: {
    possiblyLost: { sinceTurn: 7, source: 'scoreboard' },
    alibi: { afterTurn: 7, sightingTurn: 9, source: 'turnInfo.ships' },
  },
  fields: {
    shipId: { kind: 'bounded', operator: 'lte', value: 318 },
    hull: { kind: 'known', value: 13 },
    engine: { kind: 'known', value: 9 },
    beams: { kind: 'options', values: [3, 5] },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'known', value: 4 },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [
    {
      comboId: 'combo_a',
      label: 'Option A',
      solutionRankWeight: 10,
      hullId: 13,
      engineId: 9,
      beamCount: 8,
      launcherCount: 6,
    },
    {
      comboId: 'combo_b',
      label: 'Option B',
      solutionRankWeight: 3,
      hullId: 14,
      engineId: 10,
      beamCount: 4,
      launcherCount: 2,
    },
  ],
  displayDefaultOptionSetIndex: 0,
  lastSeen: { turn: 9, x: 1200, y: 800, planetId: 55 },
}

const lostRecord: FleetTableRecord = {
  recordId: 'rec-lost',
  disposition: 'lost',
  qualifiers: {},
  fields: {
    shipId: { kind: 'known', value: 42 },
    hull: { kind: 'unknown' },
    engine: { kind: 'unknown' },
    beams: { kind: 'unknown' },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'unknown' },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [],
}

const players = [
  { ordinal: 1, playerId: 8, name: 'Alice', raceName: null },
  { ordinal: 2, playerId: 9, name: 'Bob', raceName: null },
] as const

const fleetWire: FleetTableWire = {
  analyticId: 'fleet',
  defaultActiveOnly: true,
  players: [
    {
      playerId: 8,
      playerName: 'Alice',
      discrepancy: {
        hostTurn: 111,
        activeRowCount: 2,
        scoreboardImpliedCount: 1,
      },
      records: [activeRecord, lostRecord],
    },
    {
      playerId: 9,
      playerName: 'Bob',
      records: [],
    },
  ],
}

describe('FleetPlayerTableTile', () => {
  it('renders only active disposition rows', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[activeRecord, lostRecord]}
      />
    )

    expect(screen.getByText('<= 318')).toBeInTheDocument()
    expect(screen.queryByText('42')).not.toBeInTheDocument()
  })

  it('shows discrepancy banner in the tile header', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[activeRecord]}
        discrepancy={{
          hostTurn: 111,
          activeRowCount: 2,
          scoreboardImpliedCount: 1,
        }}
      />
    )

    expect(
      screen.getByRole('status', {
        name: 'Fleet count discrepancy on turn 111: 2 active rows vs 1 implied by scoreboard',
      })
    ).toBeInTheDocument()
  })

  it('expands alternate build option sets from the row expander', async () => {
    const user = userEvent.setup()
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[activeRecord]}
      />
    )

    expect(screen.queryByText(/Option B/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Expand build options for rec-active' }))

    expect(screen.getByText(/Option B/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Collapse build options for rec-active' })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
  })

  it('renders status icons for qualifiers', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[activeRecord]}
      />
    )

    expect(screen.getByLabelText('Possibly lost since turn 7')).toBeInTheDocument()
    expect(screen.getByLabelText('Alibi after turn 7')).toBeInTheDocument()
  })
})

describe('FleetTableView', () => {
  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
  })

  it('sorts the viewpoint player tile first', () => {
    render(
      <FleetTableView
        data={fleetWire}
        players={[...players]}
        viewpointPlayerId={9}
      />
    )

    const tiles = screen.getAllByRole('region', { name: /fleet table$/i })
    expect(tiles).toHaveLength(2)
    expect(within(tiles[0]).getByRole('heading', { level: 3 })).toHaveTextContent('Bob')
    expect(within(tiles[1]).getByRole('heading', { level: 3 })).toHaveTextContent('Alice')
  })

  it('hides tiles for players turned off in fleet visibility', () => {
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(9, false)

    render(
      <FleetTableView
        data={fleetWire}
        players={[...players]}
        viewpointPlayerId={8}
      />
    )

    expect(screen.getByRole('region', { name: 'Alice fleet table' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Bob fleet table' })).not.toBeInTheDocument()
  })
})
