import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { fetchAnalyticMap } from '../../api/bff'
import { HomeworldLocatorTableTile } from './HomeworldLocatorTableTile'
import { fetchHomeworldLocatorMap, fetchHomeworldLocatorTable } from './api'

vi.mock('./api', () => ({
  fetchHomeworldLocatorTable: vi.fn(),
  fetchHomeworldLocatorMap: vi.fn(),
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

function annularVertices(angleStart: number, angleEnd: number) {
  const rOuter = 200
  const rInner = 100
  return [
    { x: rOuter * Math.cos(angleStart), y: rOuter * Math.sin(angleStart) },
    { x: rOuter * Math.cos(angleEnd), y: rOuter * Math.sin(angleEnd) },
    { x: rInner * Math.cos(angleEnd), y: rInner * Math.sin(angleEnd) },
    { x: rInner * Math.cos(angleStart), y: rInner * Math.sin(angleStart) },
  ]
}

const annularEdges = [
  { type: 'arc' as const, centerX: 0, centerY: 0, clockwise: false },
  { type: 'line' as const },
  { type: 'arc' as const, centerX: 0, centerY: 0, clockwise: true },
  { type: 'line' as const },
]

function renderTile(fetchEnabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return render(
    <HomeworldLocatorTableTile
      analyticScope={{ gameId: '628580', turn: 5, perspective: 1, username: 'alice' }}
      fetchEnabled={fetchEnabled}
    />,
    { wrapper }
  )
}

describe('HomeworldLocatorTableTile', () => {
  beforeEach(() => {
    vi.mocked(fetchHomeworldLocatorTable).mockReset()
    vi.mocked(fetchHomeworldLocatorMap).mockReset()
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

  it('shows candidate rows and a degraded baseline note', async () => {
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
        {
          planetId: 44,
          perspective: null,
          confidenceTier: 'possible',
          attribution: 'inferred',
          assertedCue: false,
          locationAsserted: false,
          isMostProbable: true,
        },
      ],
    })
    renderTile()
    expect(await screen.findByRole('status')).toHaveTextContent(/Baseline degraded/)
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('Slot 1')).toBeInTheDocument()
    expect(screen.getByText('Orphan')).toBeInTheDocument()
    expect(screen.getByText('Definite')).toBeInTheDocument()
    expect(screen.getByText('Possible (most probable)')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Asserted' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /assert hw/i })).not.toBeInTheDocument()
  })

  it('shows inactive hint when the analytic is unavailable', async () => {
    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: false,
      inactiveReason: 'nohomeworld',
      baselineDegraded: false,
      baselineTurn: null,
      rows: [],
    })
    renderTile()
    expect(await screen.findByText(/no homeworld planets/i)).toBeInTheDocument()
  })

  it('groups candidates into sector accordion when overlays resolve', async () => {
    const north = {
      kind: 'homeworld-sector' as const,
      id: 'homeworld-sector-1',
      fillColor: '#f97316',
      fillOpacity: 0,
      playerLabel: 'alice (The Federation)',
      candidateCount: 1,
      geometry: {
        type: 'boundary' as const,
        vertices: annularVertices(Math.PI / 4, (3 * Math.PI) / 4),
        edges: annularEdges,
      },
    }
    const east = {
      kind: 'homeworld-sector' as const,
      id: 'homeworld-sector-0',
      fillColor: '#f97316',
      fillOpacity: 0,
      candidateCount: 1,
      geometry: {
        type: 'boundary' as const,
        vertices: annularVertices(-Math.PI / 4, Math.PI / 4),
        edges: annularEdges,
      },
    }

    vi.mocked(fetchHomeworldLocatorTable).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      inactiveReason: null,
      baselineDegraded: false,
      rows: [
        {
          planetId: 101,
          perspective: 1,
          confidenceTier: 'definite',
          attribution: 'inferred',
          assertedCue: false,
          locationAsserted: false,
          isMostProbable: false,
        },
        {
          planetId: 100,
          perspective: null,
          confidenceTier: 'possible',
          attribution: 'inferred',
          assertedCue: false,
          locationAsserted: false,
          isMostProbable: true,
        },
      ],
    })
    vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [east, north],
      markers: [],
    })
    vi.mocked(fetchAnalyticMap).mockResolvedValue({
      analyticId: 'base-map',
      nodes: [
        { id: 'base-map:p101', label: '101', x: 0, y: 150, planet: { id: 101 } },
        { id: 'base-map:p100', label: '100', x: 150, y: 0, planet: { id: 100 } },
      ],
      edges: [],
    })

    renderTile()
    expect(
      await screen.findByRole('button', { name: /toggle sector selection: alice/i })
    ).toBeInTheDocument()
    const titles = screen.getAllByRole('button', { name: /toggle sector selection/i })
    expect(titles.map((el) => el.textContent)).toEqual([
      'alice (The Federation)',
      'Unknown',
    ])
    expect(screen.getByText('101')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /assert hw/i })).not.toBeInTheDocument()
  })
})
