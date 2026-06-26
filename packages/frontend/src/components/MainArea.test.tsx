import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticItem, AnalyticShellScope, ConnectionsMapParams } from '../api/bff'
import type { ScoresTableParams } from '../analytics/scores/api'
import { MainArea } from './MainArea'
import { fetchAnalyticTable } from '../api/bff'
import { useMapAnalyticQueries } from '../lib/useMapAnalyticQueries'
import { useRetainedMapDisplay } from '../lib/useRetainedMapDisplay'
import { useStellarCartographyMapContext } from '../lib/useStellarCartographyMapContext'
import { buildStellarCartographyMapContext, defaultStellarCartographyMapUiConfig } from '../analytics/stellar-cartography/mapUiConfig'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
  }
})

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

vi.mock('../lib/useStellarCartographyMapContext', () => ({
  useStellarCartographyMapContext: vi.fn(),
}))

vi.mock('./shell/MapShellContent', () => ({
  MapShellContent: () => <div data-testid="map-shell-content" />,
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
    id: 'scores',
    name: 'Scores',
    supportsTable: true,
    supportsMap: false,
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

const defaultScoresTableParams: ScoresTableParams = {
  includeBuildInference: false,
}

const idleGlobalInferencePause = {
  isGloballyPaused: false,
  isPending: false,
  error: null,
  pauseGlobally: vi.fn(),
  resumeGlobally: vi.fn(),
  syncPausedFromStream: vi.fn(),
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
    scoresTableParams: defaultScoresTableParams,
    scoresPreferencesHydrated: true,
    globalInferencePause: idleGlobalInferencePause,
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
      mapError: null,
      mapQueries: [],
    })
    vi.mocked(useRetainedMapDisplay).mockReturnValue({
      mapShellView: { phase: 'full-loading', loadingMessage: 'Loading map…' },
    })
    vi.mocked(useStellarCartographyMapContext).mockReturnValue(
      buildStellarCartographyMapContext(defaultStellarCartographyMapUiConfig(), sampleScope)
    )
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

  it('does not subscribe to cartography config when that analytic is disabled', () => {
    render(<MainArea {...defaultMainAreaProps('map')} />, { wrapper: createWrapper() })

    expect(useStellarCartographyMapContext).not.toHaveBeenCalled()
  })

  it('subscribes to live cartography config only when that analytic is enabled', () => {
    vi.mocked(useMapAnalyticQueries).mockReturnValue({
      enabledMapIds: ['connections', 'stellar-cartography'],
      mapIds: ['base-map', 'connections', 'stellar-cartography'],
      combined: emptyCombined,
      pending: false,
      hasError: false,
      hasAnyData: false,
      mapError: null,
      mapQueries: [],
    })

    render(
      <MainArea
        {...defaultMainAreaProps('map')}
        enabledAnalyticIds={['connections', 'stellar-cartography']}
      />,
      { wrapper: createWrapper() }
    )

    expect(useStellarCartographyMapContext).toHaveBeenCalledTimes(1)
    expect(useStellarCartographyMapContext).toHaveBeenCalledWith(sampleScope)
  })
})

describe('MainArea tabular analytic sections', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'connections',
      columns: ['From', 'To'],
      rows: [['A', 'B']],
    })
  })

  it('collapses and expands the analytic table body from the title line', async () => {
    const user = userEvent.setup()

    render(<MainArea {...defaultMainAreaProps('tabular')} />, { wrapper: createWrapper() })

    expect(await screen.findByText('B')).toBeInTheDocument()

    const toggle = screen.getByRole('button', { name: 'Collapse Connections' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveAccessibleName('Expand Connections')
    expect(screen.queryByText('B')).not.toBeInTheDocument()

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByText('B')).toBeInTheDocument()
  })

  it('does not fetch scores table until preferences are hydrated', async () => {
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'scores',
      columns: ['Player'],
      rows: [['Alice']],
    })

    render(
      <MainArea
        {...defaultMainAreaProps('tabular')}
        enabledAnalyticIds={['scores']}
        scoresPreferencesHydrated={false}
      />,
      { wrapper: createWrapper() }
    )

    expect(screen.getByText('Loading…')).toBeInTheDocument()
    expect(fetchAnalyticTable).not.toHaveBeenCalled()
  })
})
