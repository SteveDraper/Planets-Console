import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { fetchAnalyticMap } from '../../api/bff'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { perspectiveRow } from '../../lib/perspectiveRowTestFixtures'
import { HomeworldLocatorPanel } from './HomeworldLocatorPanel'
import {
  fetchHomeworldLocatorMap,
  fetchHomeworldLocatorTable,
  postHomeworldLocatorRefresh,
} from './api'

vi.mock('./api', () => ({
  fetchHomeworldLocatorTable: vi.fn(),
  fetchHomeworldLocatorMap: vi.fn(),
  postHomeworldLocatorAssertion: vi.fn(),
  postHomeworldLocatorRefresh: vi.fn(),
}))

vi.mock('../../api/bff', async () => {
  const actual = await vi.importActual<typeof import('../../api/bff')>('../../api/bff')
  return {
    ...actual,
    fetchAnalyticMap: vi.fn().mockResolvedValue({
      analyticId: 'base-map',
      nodes: [],
      edges: [],
    }),
  }
})

function renderPanel(
  roster: readonly PerspectiveRow[] = [
    perspectiveRow(1, 'alice', { raceName: 'The Federation' }),
  ]
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return render(
    <HomeworldLocatorPanel
      analyticScope={{ gameId: '628580', turn: 5, perspective: 1, username: 'alice' }}
      fetchEnabled
      roster={roster}
      selectedPlanetId={null}
      onSelectPlanet={() => undefined}
    />,
    { wrapper }
  )
}

describe('HomeworldLocatorPanel', () => {
  beforeEach(() => {
    vi.mocked(fetchHomeworldLocatorTable).mockReset()
    vi.mocked(fetchHomeworldLocatorMap).mockReset()
    vi.mocked(postHomeworldLocatorRefresh).mockReset()
    vi.mocked(fetchAnalyticMap).mockReset()
    vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [],
      markers: [],
    })
    vi.mocked(fetchAnalyticMap).mockResolvedValue({
      analyticId: 'base-map',
      nodes: [],
      edges: [],
    })
  })

  it('renders read-only candidate rows without assert controls', async () => {
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      inactiveReason: null,
      baselineDegraded: true,
      baselineTurn: 4,
      rows: [
        {
          planetId: 12,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'inferred',
          assertedCue: false,
          locationAsserted: false,
          isMostProbable: false,
        },
      ],
    })

    renderPanel()
    expect(await screen.findByRole('status')).toHaveTextContent(/Baseline degraded/)
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('alice (The Federation)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /assert hw/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/assert ownership/i)).not.toBeInTheDocument()
  })

  it('surfaces base-map query failure when sector overlays require positions', async () => {
    const sectorOverlay = {
      kind: 'homeworld-sector' as const,
      id: 'homeworld-sector-2',
      fillColor: '#f97316',
      fillOpacity: 0,
      geometry: {
        type: 'boundary' as const,
        vertices: [
          { x: 0, y: 0 },
          { x: 1, y: 0 },
          { x: 1, y: 1 },
          { x: 0, y: 1 },
        ],
        edges: [
          { type: 'line' as const },
          { type: 'line' as const },
          { type: 'line' as const },
          { type: 'line' as const },
        ],
      },
    }
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      inactiveReason: null,
      baselineDegraded: false,
      rows: [
        {
          planetId: 12,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'inferred',
          assertedCue: false,
          locationAsserted: false,
          isMostProbable: false,
        },
      ],
    })
    vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [sectorOverlay],
      markers: [],
    })
    vi.mocked(fetchAnalyticMap).mockRejectedValue(new Error('base map unavailable'))

    renderPanel()

    expect(await screen.findByRole('alert')).toHaveTextContent(/base map unavailable/i)
    expect(screen.getByText('12')).toBeInTheDocument()
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
