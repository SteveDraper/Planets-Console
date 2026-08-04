import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
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
    vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [],
      markers: [],
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
