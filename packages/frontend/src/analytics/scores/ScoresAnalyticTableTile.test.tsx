import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ScoresAnalyticTableTile } from './ScoresAnalyticTableTile'
import { useScoresTablePreferencesStore } from '../../stores/scoresTablePreferences'
import { BUILD_INFERENCE_COLUMN } from './scoresTableColumns'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
    fetchScoresTableInferenceStream: vi.fn(() => new Promise(() => {})),
  }
})

vi.mock('../../lib/usePersistStoreHydrated', () => ({
  usePersistStoreHydrated: vi.fn(() => true),
}))

import { fetchAnalyticTable } from '../../api/bff'

const sampleScope = { gameId: '628580', turn: 111, perspective: 1 }

function renderTile(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

describe('ScoresAnalyticTableTile', () => {
  beforeEach(() => {
    vi.mocked(fetchAnalyticTable).mockReset()
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'scores',
      columns: ['Race / Player'],
      rows: [['The Birds (1)']],
      buildInferenceAvailable: true,
    })
    useScoresTablePreferencesStore.setState({
      scoresTableParams: { includeBuildInference: false },
    })
  })

  it('fetches with analyticId from table-view props', async () => {
    renderTile(
      <ScoresAnalyticTableTile
        analyticId="from-table-view-props"
        analyticScope={sampleScope}
        fetchEnabled
      />
    )

    expect(await screen.findByRole('cell', { name: 'The Birds (1)' })).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })
    expect(fetchAnalyticTable).toHaveBeenCalledWith('from-table-view-props', sampleScope)
  })

  it('renders the shared fallback grid from the same query without a second fetch', async () => {
    renderTile(
      <ScoresAnalyticTableTile
        analyticId="scores"
        analyticScope={sampleScope}
        fetchEnabled
      />
    )

    expect(await screen.findByRole('columnheader', { name: 'Race / Player' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Build inference in progress')).toBeNull()
    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })
  })

  it('keeps the inference table when build inference is included', async () => {
    useScoresTablePreferencesStore.setState({
      scoresTableParams: { includeBuildInference: true },
    })
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'scores',
      columns: ['Race (player)', BUILD_INFERENCE_COLUMN],
      rows: [['The Birds (1)']],
      includeBuildInference: true,
      buildInferenceAvailable: true,
      inferenceByRow: [{ playerId: 1 }],
    })

    renderTile(
      <ScoresAnalyticTableTile
        analyticId="scores"
        analyticScope={sampleScope}
        fetchEnabled
      />
    )

    expect(await screen.findByLabelText('Build inference in progress')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Build inference/ })).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })
    expect(fetchAnalyticTable).toHaveBeenCalledWith('scores', sampleScope)
  })
})
