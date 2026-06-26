import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { FleetAnalyticTableTile } from './FleetAnalyticTableTile'

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

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('FleetAnalyticTableTile', () => {
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
