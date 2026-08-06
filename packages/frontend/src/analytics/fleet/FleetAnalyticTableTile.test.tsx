import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'
import { FleetAnalyticTableTile } from './FleetAnalyticTableTile'
import { pendingFleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { seedShellViewpoint, FLEET_TEST_SHELL_PLAYERS } from './fleetTestShell'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
    fetchFleetComponentCatalog: vi.fn(),
    fetchFleetTableStream: vi.fn(),
  }
})

import { fetchAnalyticTable, fetchFleetComponentCatalog, fetchFleetTableStream } from '../../api/bff'

const sampleScope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
}

function pendingStreamPlayersById() {
  return new Map(
    FLEET_TEST_SHELL_PLAYERS.map((player) => [
      player.playerId,
      pendingFleetPlayerStreamSlice(),
    ])
  )
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('FleetAnalyticTableTile', () => {
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
    seedShellViewpoint(1)
    vi.mocked(fetchFleetComponentCatalog).mockResolvedValue({
      hulls: { '13': 'Cruiser A' },
      engines: {},
      beams: {},
      torpedoes: {},
    })
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'scores',
      columns: ['Race (player)'],
      rows: [],
      rowPlayerIds: [],
    })
    vi.mocked(fetchFleetTableStream).mockImplementation(async () => {})
  })

  it('renders visible player tiles immediately in pending state before stream events', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <FleetAnalyticTableTile
        analyticScope={sampleScope}
        fetchEnabled
        streamPlayersById={pendingStreamPlayersById()}
      />,
      { wrapper: createWrapper(client) }
    )

    expect(screen.getByRole('region', { name: 'Alice fleet table' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Bob fleet table' })).toBeInTheDocument()
    expect(screen.getAllByText('Fleet materialization in progress')).toHaveLength(2)
    expect(screen.getAllByText('Waiting for fleet records.')).toHaveLength(2)
  })

  it('loads component catalog without owning the fleet stream connect', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <FleetAnalyticTableTile
        analyticScope={sampleScope}
        fetchEnabled
        streamPlayersById={pendingStreamPlayersById()}
      />,
      { wrapper: createWrapper(client) }
    )

    await screen.findByRole('region', { name: 'Alice fleet table' })
    expect(fetchFleetComponentCatalog).toHaveBeenCalled()
    expect(fetchFleetTableStream).not.toHaveBeenCalled()
  })
})
