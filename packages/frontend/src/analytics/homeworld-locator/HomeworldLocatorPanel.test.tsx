import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { HomeworldLocatorPanel } from './HomeworldLocatorPanel'
import {
  fetchHomeworldLocatorTable,
  postHomeworldLocatorRefresh,
} from './api'

vi.mock('./api', () => ({
  fetchHomeworldLocatorTable: vi.fn(),
  fetchHomeworldLocatorMap: vi.fn(),
  postHomeworldLocatorAssertion: vi.fn(),
  postHomeworldLocatorRefresh: vi.fn(),
}))

const SECTOR_OVERLAY: MapRegionOverlay = {
  kind: 'homeworld-sector' as const,
  id: 'homeworld-sector-2',
  fillColor: '#f97316',
  fillOpacity: 0,
  playerLabel: 'Sector Two',
  geometry: {
    type: 'boundary' as const,
    vertices: [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ],
    edges: [
      { type: 'line' as const },
      { type: 'line' as const },
      { type: 'line' as const },
      { type: 'line' as const },
    ],
  },
}

const CANDIDATE_ROW = {
  planetId: 12,
  perspective: 1,
  confidenceTier: 'definite' as const,
  attribution: 'inferred' as const,
  assertedCue: false,
  locationAsserted: false,
  isMostProbable: false,
}

const EMPTY_OVERLAYS: readonly MapRegionOverlay[] = []
const EMPTY_POSITIONS: ReadonlyMap<number, { x: number; y: number }> = new Map()

const DEFAULT_ROSTER: readonly PerspectiveRow[] = [
  perspectiveRow(1, 'alice', { raceName: 'The Federation' }),
]

type PanelOptions = {
  overlays?: readonly MapRegionOverlay[]
  overlaysReady?: boolean
  planetPositions?: ReadonlyMap<number, { x: number; y: number }>
  positionsReady?: boolean
  positionsError?: unknown | null
}

function panelElement(
  roster: readonly PerspectiveRow[],
  options: PanelOptions = {}
): ReactElement {
  return (
    <HomeworldLocatorPanel
      analyticScope={{ gameId: '628580', turn: 5, perspective: 1, username: 'alice' }}
      fetchEnabled
      roster={roster}
      selectedPlanetId={null}
      onSelectPlanet={() => undefined}
      selectedSectorIndexes={new Set()}
      onToggleSectorIndex={() => undefined}
      overlays={options.overlays ?? EMPTY_OVERLAYS}
      overlaysReady={options.overlaysReady ?? true}
      planetPositions={options.planetPositions ?? EMPTY_POSITIONS}
      positionsReady={options.positionsReady ?? true}
      positionsError={options.positionsError ?? null}
    />
  )
}

function renderPanel(roster: readonly PerspectiveRow[] = DEFAULT_ROSTER, options: PanelOptions = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return render(panelElement(roster, options), { wrapper })
}

describe('HomeworldLocatorPanel', () => {
  beforeEach(() => {
    vi.mocked(fetchHomeworldLocatorTable).mockReset()
    vi.mocked(postHomeworldLocatorRefresh).mockReset()
  })

  it('renders read-only candidate rows without assert controls', async () => {
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      inactiveReason: null,
      baselineDegraded: true,
      baselineTurn: 4,
      rows: [CANDIDATE_ROW],
    })

    renderPanel()
    expect(await screen.findByRole('status')).toHaveTextContent(/Baseline degraded/)
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('alice (The Federation)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /assert hw/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/assert ownership/i)).not.toBeInTheDocument()
  })

  it('holds sector accordion on Loading… while planet positions are pending', async () => {
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      inactiveReason: null,
      baselineDegraded: false,
      rows: [CANDIDATE_ROW],
    })

    const { rerender } = renderPanel(undefined, {
      overlays: [SECTOR_OVERLAY],
      overlaysReady: true,
      positionsReady: false,
      planetPositions: EMPTY_POSITIONS,
    })

    // Table ready (Refresh visible); overlays ready but positions still pending → hold.
    expect(await screen.findByRole('button', { name: /^refresh$/i })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('Loading…')).toBeInTheDocument()
      expect(screen.queryByText('Unassigned')).not.toBeInTheDocument()
      expect(screen.queryByText('12')).not.toBeInTheDocument()
      expect(screen.queryByText('Sector Two')).not.toBeInTheDocument()
    })

    rerender(
      panelElement(DEFAULT_ROSTER, {
        overlays: [SECTOR_OVERLAY],
        overlaysReady: true,
        planetPositions: new Map([[12, { x: 50, y: 50 }]]),
        positionsReady: true,
        positionsError: null,
      })
    )

    expect(await screen.findByText('Sector Two')).toBeInTheDocument()
    expect(screen.queryByText('Unassigned')).not.toBeInTheDocument()
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()

    await userEvent.click(
      screen.getByRole('button', { name: /expand sector Sector Two/i })
    )
    expect(screen.getByText('12')).toBeInTheDocument()
  })

  it('surfaces planet-positions failure without a false Unassigned dump', async () => {
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      inactiveReason: null,
      baselineDegraded: false,
      rows: [CANDIDATE_ROW],
    })

    renderPanel(undefined, {
      overlays: [SECTOR_OVERLAY],
      overlaysReady: true,
      positionsReady: false,
      positionsError: new Error('base map unavailable'),
    })

    expect(await screen.findByRole('alert')).toHaveTextContent(/base map unavailable/i)
    expect(screen.queryByText('Unassigned')).not.toBeInTheDocument()
    expect(screen.queryByText('12')).not.toBeInTheDocument()
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })

  it('posts refresh and keeps the refresh control available', async () => {
    const user = userEvent.setup()
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      rows: [],
    })
    vi.mocked(postHomeworldLocatorRefresh).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      rows: [],
    })

    renderPanel()
    await user.click(await screen.findByRole('button', { name: /^refresh$/i }))
    await waitFor(() => {
      expect(postHomeworldLocatorRefresh).toHaveBeenCalled()
    })
  })
})
