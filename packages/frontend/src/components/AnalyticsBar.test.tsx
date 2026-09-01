import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { AnalyticsBar } from './AnalyticsBar'
import type { AnalyticItem } from '../api/bff'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
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

const catalog: AnalyticItem[] = [
  { id: 'scores', name: 'Scores', supportsTable: true, supportsMap: false, type: 'selectable' },
  {
    id: 'unregistered-selectable',
    name: 'Mystery',
    supportsTable: true,
    supportsMap: false,
    type: 'selectable',
  },
]

function renderBar(
  viewMode: 'tabular' | 'map' = 'tabular',
  enabledIds: Set<string> = new Set()
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <AnalyticsBar
      analytics={catalog}
      enabledIds={enabledIds}
      onToggle={() => {}}
      viewMode={viewMode}
      turnDataReady
      analyticScope={null}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    }
  )
}

describe('AnalyticsBar shell registration', () => {
  it('mounts a registered custom tile in the matching view mode', () => {
    renderBar('tabular', new Set(['scores']))
    expect(screen.getByText('Scores')).toBeInTheDocument()
    expect(screen.getByLabelText('Include build inference')).toBeInTheDocument()
  })

  it('uses a generic checkbox for an unregistered selectable id', () => {
    renderBar('tabular')
    expect(screen.getByText('Mystery')).toBeInTheDocument()
    const mystery = screen.getByText('Mystery').closest('label')
    expect(mystery?.querySelector('input[type="checkbox"]')).not.toBeNull()
  })

  it('falls back to a generic checkbox when a registered factory returns null', () => {
    renderBar('map', new Set(['scores']))
    expect(screen.getByText('Scores')).toBeInTheDocument()
    expect(screen.queryByLabelText('Include build inference')).not.toBeInTheDocument()
  })
})
