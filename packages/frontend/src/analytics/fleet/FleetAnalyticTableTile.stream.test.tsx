import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import * as bff from '../../api/bff'
import {
  bumpScoresInferenceRevision,
  useScoresInferenceRevisionStore,
} from '../../stores/scoresInferenceRevision'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'
import { FleetAnalyticTableTile } from './FleetAnalyticTableTile'
import { seedShellViewpoint } from './fleetTestShell'
import type { FleetTableRecord } from './fleetTableWireSchema'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
    fetchFleetComponentCatalog: vi.fn(),
    fetchFleetTableStream: vi.fn(),
  }
})

import { fetchAnalyticTable, fetchFleetComponentCatalog } from '../../api/bff'

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

const placeholderRecord: FleetTableRecord = {
  recordId: 'rec-active',
  disposition: 'active',
  qualifiers: {},
  fields: {
    shipId: { kind: 'bounded', operator: 'lte', value: 318 },
    hull: { kind: 'unknown' },
    engine: { kind: 'unknown' },
    beams: { kind: 'unknown' },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'unknown' },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [],
}

const refinedRecord: FleetTableRecord = {
  ...placeholderRecord,
  fields: {
    ...placeholderRecord.fields,
    hull: { kind: 'known', value: 13 },
    builtTurn: { kind: 'known', value: 4 },
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
  ],
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('FleetAnalyticTableTile stream integration', () => {
  beforeEach(() => {
    useScoresInferenceRevisionStore.getState().resetRevisions()
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideName: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
    seedShellViewpoint('Alice')
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
  })

  it('shows all tiles in pending state before any stream event', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    vi.mocked(bff.fetchFleetTableStream).mockImplementation(
      async () => new Promise(() => {})
    )

    render(<FleetAnalyticTableTile analyticScope={scope} fetchEnabled />, {
      wrapper: createWrapper(client),
    })

    expect(await screen.findByRole('region', { name: 'Alice fleet table' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Bob fleet table' })).toBeInTheDocument()
    expect(screen.getAllByText('Fleet materialization in progress')).toHaveLength(2)
  })

  it('updates only the targeted player tile from stream events without REST refetch', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    vi.mocked(bff.fetchFleetTableStream).mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'ledger_updated',
          playerId: 9,
          ledger: {
            playerId: 9,
            playerName: 'Bob',
            records: [refinedRecord],
          },
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 9,
          isFinal: true,
          summary: 'Bob refined',
        })
      }
    )

    render(<FleetAnalyticTableTile analyticScope={scope} fetchEnabled />, {
      wrapper: createWrapper(client),
    })

    const bobTile = await screen.findByRole('region', { name: 'Bob fleet table' })
    await waitFor(() => {
      expect(within(bobTile).getByText('Cruiser A')).toBeInTheDocument()
    })

    const aliceTile = screen.getByRole('region', { name: 'Alice fleet table' })
    expect(within(aliceTile).queryByText('Cruiser A')).not.toBeInTheDocument()
    expect(fetchFleetComponentCatalog).toHaveBeenCalled()
  })

  it('shows partial completion for one player while another remains pending', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    vi.mocked(bff.fetchFleetTableStream).mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'ledger_updated',
          playerId: 8,
          ledger: {
            playerId: 8,
            playerName: 'Alice',
            records: [placeholderRecord],
          },
        })
        await new Promise(() => {})
      }
    )

    render(<FleetAnalyticTableTile analyticScope={scope} fetchEnabled />, {
      wrapper: createWrapper(client),
    })

    const aliceTile = await screen.findByRole('region', { name: 'Alice fleet table' })
    await waitFor(() => {
      expect(within(aliceTile).getByText('<= 318')).toBeInTheDocument()
    })

    const bobTile = screen.getByRole('region', { name: 'Bob fleet table' })
    expect(within(bobTile).getByText('Fleet materialization in progress')).toBeInTheDocument()
  })

  it('shows error on one tile without hiding others', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    vi.mocked(bff.fetchFleetTableStream).mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'error',
          playerId: 9,
          detail: 'Player 9 materialization failed',
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          isFinal: true,
          summary: 'Alice ok',
        })
      }
    )

    render(<FleetAnalyticTableTile analyticScope={scope} fetchEnabled />, {
      wrapper: createWrapper(client),
    })

    const bobTile = await screen.findByRole('region', { name: 'Bob fleet table' })
    expect(within(bobTile).getByText('Player 9 materialization failed')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Alice fleet table' })).toBeInTheDocument()
  })

  it('does not refetch catalog when scores inference revision bumps', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    vi.mocked(bff.fetchFleetTableStream).mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          isFinal: true,
          summary: 'ok',
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 9,
          isFinal: true,
          summary: 'ok',
        })
      }
    )

    render(<FleetAnalyticTableTile analyticScope={scope} fetchEnabled />, {
      wrapper: createWrapper(client),
    })

    await screen.findByRole('region', { name: 'Alice fleet table' })

    const callsAfterInitialLoad = vi.mocked(fetchFleetComponentCatalog).mock.calls.length

    act(() => {
      bumpScoresInferenceRevision(scope)
    })

    await waitFor(() => {
      expect(vi.mocked(fetchFleetComponentCatalog).mock.calls.length).toBe(callsAfterInitialLoad)
    })
  })
})
