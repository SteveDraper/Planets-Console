import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'
import { FleetAnalyticTableTile } from './FleetAnalyticTableTile'
import { seedShellViewpoint } from './fleetTestShell'
import {
  loadFleetTableWireFixture,
  zodParseableFleetTableWireCases,
} from './loadFleetTableWireFixture'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
  }
})

import { fetchAnalyticTable } from '../../api/bff'

const sampleScope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
}

const goldenFleetTableWire = zodParseableFleetTableWireCases(
  loadFleetTableWireFixture().cases
)[0]!.expectedTableWire

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
      perspectiveOverrideName: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
    seedShellViewpoint('Alice')
  })

  it('renders fleet table content when wire is valid', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticTable).mockResolvedValue(goldenFleetTableWire)

    render(
      <FleetAnalyticTableTile analyticScope={sampleScope} fetchEnabled />,
      { wrapper: createWrapper(client) }
    )

    expect(
      await screen.findByRole('heading', { level: 3, name: 'koshling' })
    ).toBeInTheDocument()
    expect(screen.getByText('<= 318')).toBeInTheDocument()
  })

  it('shows a parse error when fleet table wire is invalid', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticTable).mockResolvedValue({ analyticId: 'fleet' })

    render(
      <FleetAnalyticTableTile analyticScope={sampleScope} fetchEnabled />,
      { wrapper: createWrapper(client) }
    )

    expect(
      await screen.findByText(/Error loading fleet table\./)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Fleet table payload defaultActiveOnly must be true\./)
    ).toBeInTheDocument()
  })
})
