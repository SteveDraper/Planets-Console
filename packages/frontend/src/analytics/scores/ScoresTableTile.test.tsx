import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ScoresTableTile } from './ScoresTableTile'
import { useScoresTablePreferencesStore } from '../../stores/scoresTablePreferences'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn().mockResolvedValue({
      analyticId: 'scores',
      columns: ['Race / Player'],
      rows: [['The Birds (1)']],
      buildInferenceAvailable: true,
    }),
  }
})

vi.mock('../../lib/usePersistStoreHydrated', () => ({
  usePersistStoreHydrated: vi.fn(() => true),
}))

const sampleScope = { gameId: '628580', turn: 111, perspective: 1 }

function renderTile(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

describe('ScoresTableTile', () => {
  beforeEach(async () => {
    const { fetchAnalyticTable } = await import('../../api/bff')
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

  it('shows include build inference checkbox when scores is enabled in tabular mode', async () => {
    renderTile(
      <ScoresTableTile
        name="Scores"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        turnDataReady
        analyticScope={sampleScope}
      />
    )

    const inferenceCheckbox = await screen.findByLabelText('Include build inference')
    await waitFor(() => {
      expect(inferenceCheckbox).not.toBeDisabled()
    })
    fireEvent.click(inferenceCheckbox)
    expect(useScoresTablePreferencesStore.getState().scoresTableParams).toEqual({
      includeBuildInference: true,
    })
  })

  it('hides include build inference checkbox when scores is disabled', () => {
    renderTile(
      <ScoresTableTile
        name="Scores"
        enabled={false}
        supportsMode
        depressed={false}
        onToggle={() => {}}
        turnDataReady
        analyticScope={sampleScope}
      />
    )

    expect(screen.queryByLabelText('Include build inference')).toBeNull()
  })

  it('grey-disables include build inference when availability is off', async () => {
    const { fetchAnalyticTable } = await import('../../api/bff')
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'scores',
      columns: ['Race / Player'],
      rows: [['The Birds (1)']],
      buildInferenceAvailable: false,
    })
    useScoresTablePreferencesStore.setState({
      scoresTableParams: { includeBuildInference: true },
    })
    renderTile(
      <ScoresTableTile
        name="Scores"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        turnDataReady
        analyticScope={sampleScope}
      />
    )

    const inferenceCheckbox = await screen.findByLabelText('Include build inference')
    await waitFor(() => {
      expect(inferenceCheckbox).toBeDisabled()
      expect(inferenceCheckbox).toHaveAttribute(
        'title',
        expect.stringMatching(/stealth mode/i)
      )
    })
  })

  it('keeps include build inference disabled until availability is known', () => {
    renderTile(
      <ScoresTableTile
        name="Scores"
        enabled
        supportsMode
        depressed
        onToggle={() => {}}
        turnDataReady={false}
        analyticScope={sampleScope}
      />
    )

    const inferenceCheckbox = screen.getByLabelText('Include build inference')
    expect(inferenceCheckbox).toBeDisabled()
    expect(inferenceCheckbox).not.toHaveAttribute('title')
  })
})
