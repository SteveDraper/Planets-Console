import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import { DiagnosticsHomeworldsTab } from './DiagnosticsHomeworldsTab'

vi.mock('../../api/bffLayoutPriorDiagnostics', () => ({
  fetchLayoutPriorReports: vi.fn(),
}))

import { fetchLayoutPriorReports } from '../../api/bffLayoutPriorDiagnostics'

const scope: AnalyticShellScope = { gameId: '680224', perspective: 1, turn: 40 }

const emptySnapshot = {
  shell: { gameId: '680224', perspective: 1, turn: 40 },
  reports: [] as Record<string, unknown>[],
  evidenceRefineReports: [] as Record<string, unknown>[],
  evidenceRefineSummary: {},
  baselineReports: [] as Record<string, unknown>[],
  ensureFailures: [] as Record<string, unknown>[],
}

describe('DiagnosticsHomeworldsTab', () => {
  beforeEach(() => {
    vi.mocked(fetchLayoutPriorReports).mockReset()
  })

  it('shows empty state when no reports', async () => {
    vi.mocked(fetchLayoutPriorReports).mockResolvedValue(emptySnapshot)
    render(<DiagnosticsHomeworldsTab scope={scope} onCopy={vi.fn()} isActive />)
    await waitFor(() => {
      expect(screen.getByText(/No homeworld diagnostics/i)).toBeInTheDocument()
    })
  })

  it('shows evidence-refine summary and layout-prior reports when populated', async () => {
    vi.mocked(fetchLayoutPriorReports).mockResolvedValue({
      ...emptySnapshot,
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
      evidenceRefineReports: [
        {
          turn: 14,
          timingOuter: { totalMs: 12.5 },
          timingInner: {
            originDistanceMs: 10,
            hitAppendMs: 1.5,
            singleStarbaseMs: 0.5,
          },
        },
      ],
      evidenceRefineSummary: {
        reportCount: 1,
        sumOuterTotalMs: 12.5,
        sumOriginDistanceMs: 10,
      },
      baselineReports: [
        {
          recomputed: false,
          candidateCount: 40,
          inferMs: 0,
          capturedAt: '2026-07-28T12:00:00Z',
        },
      ],
    })
    render(<DiagnosticsHomeworldsTab scope={scope} onCopy={vi.fn()} isActive />)
    await waitFor(() => {
      expect(screen.getByText(/Evidence-refine summary/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/Layout prior · anneal/i)).toBeInTheDocument()
    expect(screen.getByText(/turn 14/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Copy homeworld diagnostics/i })
    ).toBeInTheDocument()
  })

  it('shows ensure failures when populated', async () => {
    vi.mocked(fetchLayoutPriorReports).mockResolvedValue({
      ...emptySnapshot,
      ensureFailures: [
        {
          reason: 'turn_not_stored',
          missingTurn: 59,
          shellTurn: 60,
          message: 'homeworld locator cannot refine turn 60: turn 59 is not stored',
        },
      ],
    })
    render(<DiagnosticsHomeworldsTab scope={scope} onCopy={vi.fn()} isActive />)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Ensure failures/i })).toBeInTheDocument()
    })
    expect(
      screen.getAllByText(/turn 59 is not stored/i).length
    ).toBeGreaterThan(0)
  })

  it('prompts for shell when scope is null', () => {
    render(<DiagnosticsHomeworldsTab scope={null} onCopy={vi.fn()} isActive />)
    expect(screen.getByText(/Select a game, turn, and perspective/i)).toBeInTheDocument()
    expect(fetchLayoutPriorReports).not.toHaveBeenCalled()
  })
})
