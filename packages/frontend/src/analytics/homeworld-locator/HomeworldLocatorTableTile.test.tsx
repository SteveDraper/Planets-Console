import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { HomeworldLocatorTableTile } from './HomeworldLocatorTableTile'
import { fetchHomeworldLocatorTable } from './api'

vi.mock('./api', () => ({
  fetchHomeworldLocatorTable: vi.fn(),
}))

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
        },
        {
          planetId: 44,
          perspective: null,
          confidenceTier: 'possible',
          attribution: 'inferred',
        },
      ],
    })
    renderTile()
    expect(await screen.findByRole('status')).toHaveTextContent(/Baseline degraded/)
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('Slot 1')).toBeInTheDocument()
    expect(screen.getByText('Orphan')).toBeInTheDocument()
    expect(screen.getByText('Definite')).toBeInTheDocument()
    expect(screen.getByText('Possible')).toBeInTheDocument()
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
})
