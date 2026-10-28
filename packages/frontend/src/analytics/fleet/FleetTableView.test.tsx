import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement, ReactNode } from 'react'
import { FleetPlayerTableTile } from './FleetPlayerTableTile'
import { FleetTableView } from './FleetTableView'
import { pendingFleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { seedShellViewpoint } from './fleetTestShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'
import type { FleetComponentCatalog, FleetTableRecord } from './fleetTableWireSchema'

const testComponentCatalog: FleetComponentCatalog = {
  hulls: { '13': 'Cruiser A', '14': 'Cruiser B' },
  engines: { '9': 'Transwarp Drive', '10': 'Heavy Drive' },
  beams: { '3': 'Plasma Bolt', '5': 'Positron Beam' },
  torpedoes: { '6': 'Mark 4 Photon' },
}

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
      beamId: 3,
      beamCount: 8,
      launcherCount: 6,
      torpId: 6,
    },
    {
      comboId: 'combo_b',
      label: 'Option B',
      solutionRankWeight: 3,
      hullId: 14,
      engineId: 10,
      beamId: 5,
      beamCount: 4,
      launcherCount: 2,
      torpId: 6,
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

describe('FleetPlayerTableTile', () => {
  it('renders only active disposition rows', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[activeRecord, lostRecord]}
        componentCatalog={testComponentCatalog}
      />
    )

    expect(screen.getByText('Cruiser A')).toBeInTheDocument()
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

  it('shows pending progress while materializing', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[]}
        streamSlice={pendingFleetPlayerStreamSlice()}
      />
    )

    expect(screen.getByText('Fleet materialization in progress')).toBeInTheDocument()
    expect(screen.queryByText('Waiting for fleet records.')).not.toBeInTheDocument()
    expect(screen.queryByText('No active fleet records.')).not.toBeInTheDocument()
  })

  it('shows an empty body for a player with zero sightings', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[]}
        rosterPaint="sightings"
        streamSlice={pendingFleetPlayerStreamSlice()}
      />
    )

    expect(screen.queryByText('Waiting for fleet records.')).not.toBeInTheDocument()
    expect(screen.queryByText('No active fleet records.')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('keeps the empty-ledger line for a stored complete ledger', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[]}
        streamSlice={{
          discrepancyOverlay: 'inherit',
          isComplete: true,
          isFinal: true,
          isPending: false,
          summary: 'Fleet ledger loaded from cache.',
          error: null,
        }}
      />
    )

    expect(screen.getByText('No active fleet records.')).toBeInTheDocument()
  })

  it('shows the empty-ledger line for a stored ledger that is still open', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[]}
        rosterPaint="ledger"
        streamSlice={pendingFleetPlayerStreamSlice()}
      />
    )

    expect(screen.getByText('No active fleet records.')).toBeInTheDocument()
  })

  it('uses the empty status mark on sighting rows', () => {
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[
          {
            ...activeRecord,
            qualifiers: {},
            buildOptionSets: [],
          },
        ]}
        rosterPaint="sightings"
        componentCatalog={testComponentCatalog}
      />
    )

    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Possibly lost/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Alibi/)).not.toBeInTheDocument()
  })

  it('expands alternate build option sets from the row expander', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    render(
      <FleetPlayerTableTile
        playerName="Alice"
        records={[activeRecord]}
        componentCatalog={testComponentCatalog}
      />
    )

    expect(screen.queryByText(/Cruiser B/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Expand build options for rec-active' }))

    expect(screen.getByText(/Cruiser B/)).toBeInTheDocument()
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
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideOrdinal: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
  })

  function renderTable(ui: ReactElement) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(ui, {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    })
  }

  it('sorts the viewpoint player tile first', () => {
    seedShellViewpoint(2)

    const streamPlayersById = new Map([
      [8, pendingFleetPlayerStreamSlice()],
      [9, pendingFleetPlayerStreamSlice()],
    ])

    renderTable(
      <FleetTableView
        componentCatalog={testComponentCatalog}
        streamPlayersById={streamPlayersById}
        racePlayerLabels={new Map()}
      />
    )

    const tiles = screen.getAllByRole('region', { name: /fleet table$/i })
    expect(tiles).toHaveLength(2)
    expect(within(tiles[0]).getByRole('heading', { level: 3 })).toHaveTextContent('Bob')
    expect(within(tiles[1]).getByRole('heading', { level: 3 })).toHaveTextContent('Alice')
  })

  it('prefers turn-scoped scoreboard labels over shell game-info names', () => {
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [
          { ordinal: 1, playerId: 8, name: 'dead', raceName: 'The Solar Federation', eliminationTurn: 49 },
        ],
        isGameFinished: true,
        sectorDisplayName: 'Test Sector',
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
      },
      selectedTurn: 8,
      perspectiveOverrideOrdinal: 1,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(8, true)

    const streamPlayersById = new Map([[8, pendingFleetPlayerStreamSlice()]])
    const racePlayerLabels = new Map([[8, 'The Solar Federation (dougp314)']])

    renderTable(
      <FleetTableView
        componentCatalog={testComponentCatalog}
        streamPlayersById={streamPlayersById}
        racePlayerLabels={racePlayerLabels}
      />
    )

    expect(
      screen.getByRole('region', { name: 'The Solar Federation (dougp314) fleet table' })
    ).toBeInTheDocument()
  })

  it('shows race and player name in tile headings when race is known', () => {
    useShellStore.setState({
      selectedGameId: '628580',
      gameInfoContext: {
        turn: 10,
        perspectives: [
          { ordinal: 1, playerId: 8, name: 'Alice', raceName: 'The Feds', eliminationTurn: null },
          { ordinal: 2, playerId: 9, name: 'Bob', raceName: 'The Evil Empire', eliminationTurn: null },
        ],
        isGameFinished: true,
        sectorDisplayName: 'Test Sector',
        stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
        homeworldInactiveReason: null,
      },
      selectedTurn: 5,
      perspectiveOverrideOrdinal: 2,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })

    const streamPlayersById = new Map([
      [8, pendingFleetPlayerStreamSlice()],
      [9, pendingFleetPlayerStreamSlice()],
    ])

    renderTable(
      <FleetTableView
        componentCatalog={testComponentCatalog}
        streamPlayersById={streamPlayersById}
        racePlayerLabels={new Map()}
      />
    )

    expect(screen.getByRole('region', { name: 'The Evil Empire (Bob) fleet table' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'The Feds (Alice) fleet table' })).toBeInTheDocument()
  })

  it('renders painted roster rows from the stream slice', () => {
    seedShellViewpoint(1)
    const streamPlayersById = new Map([
      [
        8,
        {
          ...pendingFleetPlayerStreamSlice(),
          playerName: 'Alice',
          records: [activeRecord],
          rosterPaint: 'sightings' as const,
        },
      ],
    ])

    renderTable(
      <FleetTableView
        componentCatalog={testComponentCatalog}
        streamPlayersById={streamPlayersById}
        racePlayerLabels={new Map()}
      />
    )

    const alice = screen.getByRole('region', { name: 'Alice fleet table' })
    expect(within(alice).getByText('Cruiser A')).toBeInTheDocument()
  })

  it('keeps a blank body for an empty sighting roster on the slice', () => {
    seedShellViewpoint(1)
    const streamPlayersById = new Map([
      [
        8,
        {
          ...pendingFleetPlayerStreamSlice(),
          records: [],
          rosterPaint: 'sightings' as const,
        },
      ],
    ])

    renderTable(
      <FleetTableView
        componentCatalog={testComponentCatalog}
        streamPlayersById={streamPlayersById}
        racePlayerLabels={new Map()}
      />
    )

    const alice = screen.getByRole('region', { name: 'Alice fleet table' })
    expect(within(alice).queryByText('No active fleet records.')).not.toBeInTheDocument()
    expect(within(alice).queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows the empty-ledger line when the slice roster paint is a ledger', () => {
    seedShellViewpoint(1)
    const streamPlayersById = new Map([
      [
        8,
        {
          ...pendingFleetPlayerStreamSlice(),
          records: [],
          rosterPaint: 'ledger' as const,
        },
      ],
    ])

    renderTable(
      <FleetTableView
        componentCatalog={testComponentCatalog}
        streamPlayersById={streamPlayersById}
        racePlayerLabels={new Map()}
      />
    )

    const alice = screen.getByRole('region', { name: 'Alice fleet table' })
    expect(within(alice).getByText('No active fleet records.')).toBeInTheDocument()
  })

  it('hides tiles for players turned off in fleet visibility', () => {
    seedShellViewpoint(1)
    useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(9, false)

    const streamPlayersById = new Map([
      [8, pendingFleetPlayerStreamSlice()],
      [9, pendingFleetPlayerStreamSlice()],
    ])

    renderTable(
      <FleetTableView
        componentCatalog={testComponentCatalog}
        streamPlayersById={streamPlayersById}
        racePlayerLabels={new Map()}
      />
    )

    expect(screen.getByRole('region', { name: 'Alice fleet table' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Bob fleet table' })).not.toBeInTheDocument()
  })
})
