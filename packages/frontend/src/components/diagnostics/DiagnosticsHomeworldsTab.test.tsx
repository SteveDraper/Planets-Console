import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import { DiagnosticsHomeworldsTab } from './DiagnosticsHomeworldsTab'

vi.mock('../../api/bffLayoutPriorDiagnostics', () => ({
  fetchLayoutPriorReports: vi.fn(),
}))

import { fetchLayoutPriorReports } from '../../api/bffLayoutPriorDiagnostics'

const scope: AnalyticShellScope = { gameId: '680224', perspective: 1, turn: 40 }

describe('DiagnosticsHomeworldsTab', () => {
  beforeEach(() => {
    vi.mocked(fetchLayoutPriorReports).mockReset()
  })

  it('shows empty state when no reports', async () => {
    vi.mocked(fetchLayoutPriorReports).mockResolvedValue({
      shell: { gameId: '680224', perspective: 1, turn: 40 },
      reports: [],
    })
    render(<DiagnosticsHomeworldsTab scope={scope} onCopy={vi.fn()} isActive />)
    await waitFor(() => {
      expect(screen.getByText(/No layout-prior solver reports/i)).toBeInTheDocument()
    })
  })

  it('shows populated reports with copy controls', async () => {
    vi.mocked(fetchLayoutPriorReports).mockResolvedValue({
      shell: { gameId: '680224', perspective: 1, turn: 40 },
      reports: [
        {
          gameId: 680224,
          turn: 40,
          perspective: 1,
          solver: 'anneal',
          stopReason: 'deadline',
          capturedAt: '2026-07-28T12:00:00Z',
          search: { finalCost: 9.5 },
        },
      ],
    })
    const onCopy = vi.fn()
    render(<DiagnosticsHomeworldsTab scope={scope} onCopy={onCopy} isActive />)
    await waitFor(() => {
      expect(screen.getByText(/1 report/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/anneal · stop=deadline/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Copy homeworld layout-prior reports/i })
    ).toBeInTheDocument()
  })

  it('prompts for shell when scope is null', () => {
    render(<DiagnosticsHomeworldsTab scope={null} onCopy={vi.fn()} isActive />)
    expect(screen.getByText(/Select a game, turn, and perspective/i)).toBeInTheDocument()
    expect(fetchLayoutPriorReports).not.toHaveBeenCalled()
  })
})
