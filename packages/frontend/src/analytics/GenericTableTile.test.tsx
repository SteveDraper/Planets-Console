import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { GenericTableTile } from './GenericTableTile'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
  }
})

import { fetchAnalyticTable } from '../api/bff'

const sampleScope = { gameId: '628580', turn: 111, perspective: 1 }

function renderTile(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

describe('GenericTableTile', () => {
  beforeEach(() => {
    vi.mocked(fetchAnalyticTable).mockReset()
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'visibility',
      columns: ['Object'],
      rows: [['Planet 1']],
    })
  })

  it('asks for a turn and viewpoint when scope is missing', () => {
    renderTile(
      <GenericTableTile analyticId="visibility" analyticScope={null} fetchEnabled={false} />
    )
    expect(
      screen.getByText(/load game info and choose a turn and viewpoint/i)
    ).toBeInTheDocument()
    expect(fetchAnalyticTable).not.toHaveBeenCalled()
  })

  it('fetches with analyticId from table-view props and renders the shared grid', async () => {
    renderTile(
      <GenericTableTile analyticId="visibility" analyticScope={sampleScope} fetchEnabled />
    )

    expect(await screen.findByRole('cell', { name: 'Planet 1' })).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })
    expect(fetchAnalyticTable).toHaveBeenCalledWith('visibility', sampleScope)
  })

  it('shows the empty-grid message when the payload has no columns', async () => {
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'visibility',
      columns: undefined as unknown as string[],
      rows: [],
    })
    renderTile(
      <GenericTableTile analyticId="visibility" analyticScope={sampleScope} fetchEnabled />
    )
    expect(
      await screen.findByText('This analytic has no tabular grid view.')
    ).toBeInTheDocument()
  })
})
