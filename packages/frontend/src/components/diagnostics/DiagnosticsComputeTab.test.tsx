import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComputeDiagnosticsSnapshotResponse } from '../../api/bffComputeDiagnostics'
import { useComputeDiagnosticsStore } from '../../stores/computeDiagnostics'
import { DiagnosticsComputeTab } from './DiagnosticsComputeTab'

vi.mock('../../api/bffComputeDiagnostics', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bffComputeDiagnostics')>()
  return {
    ...actual,
    fetchComputeDiagnosticsSnapshot: vi.fn(),
  }
})

import { fetchComputeDiagnosticsSnapshot } from '../../api/bffComputeDiagnostics'

const SCOPE = { gameId: '42', perspective: 1, turn: 7 }

const NEXT_SCOPE_KEY = '42:7:1:fleet'

function snapshotFixture(): ComputeDiagnosticsSnapshotResponse {
  return {
    shell: SCOPE,
    freezeArmed: true,
    allowlistedPlayerIds: [1],
    poolQueue: [{ scopeKey: NEXT_SCOPE_KEY, analyticId: 'fleet', stepKind: 'materialize' }],
    inFlight: [],
    dagNodes: [],
    readyQueue: [{ scopeKey: NEXT_SCOPE_KEY, analyticId: 'fleet', stepKind: 'materialize' }],
    nextSingleStep: {
      target: {
        scopeKey: NEXT_SCOPE_KEY,
        analyticId: 'fleet',
        stepKind: 'materialize',
        stepIndex: 0,
        priorityBand: 'interactive',
        backend: 'local',
        source: 'held',
      },
      disabledReason: null,
    },
    completionHistory: [],
    serverStreams: [],
  }
}

describe('DiagnosticsComputeTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useComputeDiagnosticsStore.setState({
      enabled: true,
      freezeStatus: null,
      snapshot: null,
      clientStreams: [],
    })
    vi.mocked(fetchComputeDiagnosticsSnapshot).mockResolvedValue(snapshotFixture())
  })

  it('copies pool queue JSON without injecting _nextSingleStep', async () => {
    const user = userEvent.setup()
    const onCopy = vi.fn()
    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={onCopy} />)

    await waitFor(() => {
      expect(screen.getByText('Pool queue')).toBeTruthy()
    })

    expect(screen.getByTestId('next-single-step-preview').textContent).toContain(NEXT_SCOPE_KEY)
    expect(screen.queryByText(/_nextSingleStep/)).toBeNull()

    const poolHeading = screen.getByText('Pool queue')
    const poolSection = poolHeading.closest('section')
    expect(poolSection).not.toBeNull()
    await user.click(within(poolSection as HTMLElement).getByRole('button', { name: 'Copy' }))

    expect(onCopy).toHaveBeenCalledTimes(1)
    const copied = onCopy.mock.calls[0]?.[0] as string
    expect(copied).toContain(NEXT_SCOPE_KEY)
    expect(copied).not.toContain('_nextSingleStep')
    expect(JSON.parse(copied)).toEqual(snapshotFixture().poolQueue)
  })
})
