import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope, TableDataResponse } from '../../api/bff'
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
    fetchFleetTableStream: vi.fn(),
  }
})

import { fetchAnalyticTable } from '../../api/bff'

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

const fleetWire = {
  analyticId: 'fleet' as const,
  defaultActiveOnly: true as const,
  componentCatalog: {
    hulls: { '13': 'Cruiser A' },
    engines: {},
    beams: {},
    torpedoes: {},
  },
  players: [
    {
      playerId: 8,
      playerName: 'Alice',
      records: [placeholderRecord],
    },
    {
      playerId: 9,
      playerName: 'Bob',
      records: [placeholderRecord],
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
    vi.mocked(fetchAnalyticTable).mockResolvedValue(fleetWire as unknown as TableDataResponse)
  })

  it('updates only the targeted player tile from stream events without REST refetch', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    vi.mocked(bff.fetchFleetTableStream).mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'record_refined',
          playerId: 9,
          record: refinedRecord,
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
    expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
  })

  it('does not refetch REST when scores inference revision bumps', async () => {
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

    const callsAfterInitialLoad = vi.mocked(fetchAnalyticTable).mock.calls.length

    act(() => {
      bumpScoresInferenceRevision(scope)
    })

    await waitFor(() => {
      expect(vi.mocked(fetchAnalyticTable).mock.calls.length).toBe(callsAfterInitialLoad)
    })
  })
})
