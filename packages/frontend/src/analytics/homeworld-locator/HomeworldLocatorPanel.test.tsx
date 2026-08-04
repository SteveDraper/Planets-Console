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
  postHomeworldLocatorAssertion,
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

function renderPanel(roster: readonly PerspectiveRow[] = [perspectiveRow(1, 'alice', { raceName: 'The Federation' })]) {
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
    vi.mocked(postHomeworldLocatorAssertion).mockReset()
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

  it('renders interactive assert controls and posts location upsert', async () => {
    const user = userEvent.setup()
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
    vi.mocked(postHomeworldLocatorAssertion).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: true,
      baselineTurn: 4,
      rows: [
        {
          planetId: 12,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'user_asserted',
          assertedCue: true,
          locationAsserted: true,
          isMostProbable: false,
        },
      ],
    })

    renderPanel()
    expect(await screen.findByRole('status')).toHaveTextContent(/Baseline degraded/)
    expect(screen.getByRole('option', { name: 'alice (The Federation)' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /assert hw/i }))
    await waitFor(() => {
      expect(postHomeworldLocatorAssertion).toHaveBeenCalledWith(
        expect.objectContaining({ gameId: '628580', turn: 5, perspective: 1 }),
        { axis: 'location', action: 'upsert', planetId: 12 }
      )
    })
  })

  it('hides ownership controls until map query succeeds', async () => {
    let resolveMap!: (value: Awaited<ReturnType<typeof fetchHomeworldLocatorMap>>) => void
    const mapDeferred = new Promise<Awaited<ReturnType<typeof fetchHomeworldLocatorMap>>>((resolve) => {
      resolveMap = resolve
    })
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
    vi.mocked(fetchHomeworldLocatorMap).mockReturnValue(mapDeferred)

    renderPanel()

    expect(await screen.findByText('12')).toBeInTheDocument()
    expect(screen.queryByLabelText(/assert ownership for planet 12/i)).not.toBeInTheDocument()

    resolveMap({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [],
      markers: [],
    })

    expect(await screen.findByLabelText(/assert ownership for planet 12/i)).toBeInTheDocument()
  })

  it('hides ownership controls until base-map query succeeds when sectors exist', async () => {
    let resolveBaseMap!: (value: Awaited<ReturnType<typeof fetchAnalyticMap>>) => void
    const baseMapDeferred = new Promise<Awaited<ReturnType<typeof fetchAnalyticMap>>>((resolve) => {
      resolveBaseMap = resolve
    })
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
    vi.mocked(fetchAnalyticMap).mockReturnValue(baseMapDeferred)

    renderPanel()

    expect(await screen.findByText('12')).toBeInTheDocument()
    expect(screen.queryByLabelText(/assert ownership for planet 12/i)).not.toBeInTheDocument()

    resolveBaseMap({
      analyticId: 'base-map',
      nodes: [
        {
          id: 'base-map:p12',
          label: '12',
          x: 0.5,
          y: 0.5,
          planet: { id: 12 },
        },
      ],
      edges: [],
    })

    expect(await screen.findByLabelText(/assert ownership for planet 12/i)).toBeInTheDocument()
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
    expect(screen.queryByLabelText(/assert ownership for planet 12/i)).not.toBeInTheDocument()
    // Location asserts still work without base-map positions.
    expect(screen.getByRole('button', { name: /assert hw/i })).toBeInTheDocument()
  })

  it('posts ownership upsert with perspective slot ordinal, not host playerId', async () => {
    const user = userEvent.setup()
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      inactiveReason: null,
      baselineDegraded: false,
      rows: [
        {
          planetId: 12,
          perspective: 2,
          confidenceTier: 'definite',
          attribution: 'inferred',
          assertedCue: false,
          locationAsserted: false,
          isMostProbable: false,
        },
      ],
    })
    vi.mocked(postHomeworldLocatorAssertion).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      rows: [],
    })

    renderPanel([
      perspectiveRow(2, 'bob', { playerId: 847, raceName: 'The Lizards' }),
    ])

    const ownerSelect = await screen.findByLabelText(/assert ownership for planet 12/i)
    await user.selectOptions(ownerSelect, '2')

    await waitFor(() => {
      expect(postHomeworldLocatorAssertion).toHaveBeenCalledWith(
        expect.objectContaining({ gameId: '628580', turn: 5, perspective: 1 }),
        {
          axis: 'ownership',
          action: 'upsert',
          ownerSlot: 2,
          planetId: 12,
          sectorIndex: null,
        }
      )
    })
  })

  it('posts sector-keyed ownership upsert when sector overlays and planet position resolve', async () => {
    const user = userEvent.setup()
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
        edges: [{ type: 'line' as const }, { type: 'line' as const }, { type: 'line' as const }, { type: 'line' as const }],
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
    vi.mocked(fetchAnalyticMap).mockResolvedValue({
      analyticId: 'base-map',
      nodes: [
        {
          id: 'base-map:p12',
          label: '12',
          x: 0.5,
          y: 0.5,
          planet: { id: 12 },
        },
      ],
      edges: [],
    })
    vi.mocked(postHomeworldLocatorAssertion).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      rows: [],
    })

    renderPanel()

    const ownerSelect = await screen.findByLabelText(/assert ownership for planet 12/i)
    await user.selectOptions(ownerSelect, '1')

    await waitFor(() => {
      expect(postHomeworldLocatorAssertion).toHaveBeenCalledWith(
        expect.objectContaining({ gameId: '628580', turn: 5, perspective: 1 }),
        {
          axis: 'ownership',
          action: 'upsert',
          ownerSlot: 1,
          planetId: 12,
          sectorIndex: 2,
        }
      )
    })
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
