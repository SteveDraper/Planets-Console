import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticItem, AnalyticShellScope, ConnectionsMapParams } from '../api/bff'
import { MainArea } from './MainArea'
import { useMapAnalyticQueries } from '../lib/useMapAnalyticQueries'
import { useRetainedMapDisplay } from '../lib/useRetainedMapDisplay'

vi.mock('../lib/useMapAnalyticQueries', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/useMapAnalyticQueries')>()
  return {
    ...actual,
    useMapAnalyticQueries: vi.fn(),
  }
})

vi.mock('../lib/useRetainedMapDisplay', () => ({
  useRetainedMapDisplay: vi.fn(),
}))

const defaultConnectionsParams: ConnectionsMapParams = {
  warpSpeed: 9,
  gravitonicMovement: false,
  flareMode: 'off',
  flareDepth: 2,
}

const sampleAnalytics: AnalyticItem[] = [
  { id: 'base-map', name: 'Base', supportsTable: false, supportsMap: true, type: 'base' },
  {
    id: 'connections',
    name: 'Connections',
    supportsTable: true,
    supportsMap: true,
    type: 'selectable',
  },
  {
    id: 'stellar-cartography',
    name: 'Stellar Cartography',
    supportsTable: false,
    supportsMap: true,
    type: 'selectable',
  },
]

const sampleScope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
}

const emptyCombined = {
  nodes: [],
  edges: [],
  routeWaypoints: [],
  overlayCircles: [],
  wormholeUnknownEntrances: [],
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function defaultMainAreaProps(viewMode: 'tabular' | 'map') {
  return {
    viewMode,
    enabledAnalyticIds: ['connections'],
    analytics: sampleAnalytics,
    analyticScope: sampleScope,
    turnDataReady: true,
    turnEnsurePending: false,
    turnEnsureIsError: false,
    turnEnsureError: null,
    turnBlockedNoLogin: false,
    connectionsMapParams: defaultConnectionsParams,
    futureTurnOffset: 0,
    onMapZoomChange: vi.fn(),
    onSetZoomReady: vi.fn(),
  }
}

describe('MainArea map hook mounting', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useMapAnalyticQueries).mockReturnValue({
      enabledMapIds: ['connections'],
      mapIds: ['base-map', 'connections'],
      combined: emptyCombined,
      pending: false,
      hasError: false,
      hasAnyData: false,
      mapQueries: [],
    })
    vi.mocked(useRetainedMapDisplay).mockReturnValue({
      mapShellView: { phase: 'full-loading', loadingMessage: 'Loading map…' },
    })
  })

  it('does not run map hooks in tabular mode', () => {
    render(<MainArea {...defaultMainAreaProps('tabular')} />, { wrapper: createWrapper() })

    expect(useMapAnalyticQueries).not.toHaveBeenCalled()
    expect(useRetainedMapDisplay).not.toHaveBeenCalled()
  })

  it('runs map hooks only in map mode', () => {
    render(<MainArea {...defaultMainAreaProps('map')} />, { wrapper: createWrapper() })

    expect(useMapAnalyticQueries).toHaveBeenCalledTimes(1)
    expect(useRetainedMapDisplay).toHaveBeenCalledTimes(1)
  })

  it('shows turn-loading in tabular mode without map hooks', () => {
    render(
      <MainArea
        {...defaultMainAreaProps('tabular')}
        turnDataReady={false}
        turnEnsurePending={true}
      />,
      { wrapper: createWrapper() }
    )

    expect(useMapAnalyticQueries).not.toHaveBeenCalled()
    expect(screen.getByText('Loading turn data…')).toBeInTheDocument()
  })
})
