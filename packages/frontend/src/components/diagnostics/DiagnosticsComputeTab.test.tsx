import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComputeDiagnosticsSnapshotResponse } from '../../api/bffComputeDiagnostics'
import { useComputeDiagnosticsStore } from '../../stores/computeDiagnostics'
import {
  DiagnosticsComputeTab,
  snapshotHasNextStep,
  snapshotHasPendingPoolWork,
} from './DiagnosticsComputeTab'

vi.mock('../../api/bffComputeDiagnostics', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bffComputeDiagnostics')>()
  return {
    ...actual,
    fetchComputeDiagnosticsSnapshot: vi.fn(),
    postComputeDiagnosticsSingleStep: vi.fn(),
    putComputeDiagnosticsAllowlist: vi.fn(),
  }
})

import {
  fetchComputeDiagnosticsSnapshot,
  postComputeDiagnosticsSingleStep,
  putComputeDiagnosticsAllowlist,
} from '../../api/bffComputeDiagnostics'

const SCOPE = { gameId: '42', perspective: 1, turn: 7 }

const NEXT_SCOPE_KEY = '42:7:1:fleet'

function snapshotFixture(
  overrides: Partial<ComputeDiagnosticsSnapshotResponse> = {}
): ComputeDiagnosticsSnapshotResponse {
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
    ...overrides,
  }
}

function idleSnapshot(
  overrides: Partial<ComputeDiagnosticsSnapshotResponse> = {}
): ComputeDiagnosticsSnapshotResponse {
  return snapshotFixture({
    poolQueue: [],
    readyQueue: [],
    nextSingleStep: {
      target: null,
      disabledReason: 'nothing_steppable',
    },
    ...overrides,
  })
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
    vi.mocked(putComputeDiagnosticsAllowlist).mockImplementation(async (_scope, playerIds) =>
      idleSnapshot({ allowlistedPlayerIds: [...playerIds] })
    )
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

  it('Run single-steps until the focus set has no remaining work, refreshing each step', async () => {
    const user = userEvent.setup()
    const afterFirst = snapshotFixture({
      poolQueue: [],
      readyQueue: [{ scopeKey: 'scores@t5', analyticId: 'scores', stepKind: 'materialize' }],
      nextSingleStep: {
        target: {
          scopeKey: 'scores@t5',
          analyticId: 'scores',
          stepKind: 'materialize',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          backend: 'inline',
          source: 'would_dispatch',
        },
        disabledReason: null,
      },
    })
    vi.mocked(postComputeDiagnosticsSingleStep)
      .mockResolvedValueOnce(afterFirst)
      .mockResolvedValueOnce(idleSnapshot())
    vi.mocked(fetchComputeDiagnosticsSnapshot)
      .mockResolvedValueOnce(snapshotFixture())
      .mockResolvedValueOnce(idleSnapshot())

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run')).toBeTruthy()
    })

    await user.click(screen.getByTestId('compute-diagnostics-run'))

    await waitFor(() => {
      expect(postComputeDiagnosticsSingleStep).toHaveBeenCalledTimes(2)
    })
    await waitFor(() => {
      expect(screen.getByTestId('next-single-step-preview').textContent).toContain(
        'Nothing in the focus set is ready to step'
      )
    })
    expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
  })

  it('Run waits for in-flight pool work before stopping', async () => {
    const user = userEvent.setup()
    const afterStep = snapshotFixture({
      poolQueue: [],
      readyQueue: [],
      inFlight: [
        {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          stepKind: 'materialize',
          stepIndex: 0,
        },
      ],
      dagNodes: [
        {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          state: 'running',
          stepKind: 'materialize',
          stepIndex: 0,
        },
      ],
      nextSingleStep: {
        target: null,
        disabledReason: 'nothing_steppable',
      },
    })
    vi.mocked(postComputeDiagnosticsSingleStep).mockResolvedValueOnce(afterStep)
    vi.mocked(fetchComputeDiagnosticsSnapshot)
      .mockResolvedValueOnce(snapshotFixture())
      .mockResolvedValueOnce(afterStep)
      .mockResolvedValueOnce(idleSnapshot())
      .mockResolvedValueOnce(idleSnapshot())

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run')).toBeEnabled()
    })

    await user.click(screen.getByTestId('compute-diagnostics-run'))

    await waitFor(() => {
      expect(postComputeDiagnosticsSingleStep).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(fetchComputeDiagnosticsSnapshot.mock.calls.length).toBeGreaterThanOrEqual(4)
    })
    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
    })
  })

  it('Run stops with an error when single-step keeps returning the same would_dispatch target', async () => {
    const user = userEvent.setup()
    const stuck = snapshotFixture({
      poolQueue: [],
      readyQueue: [
        {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          stepKind: 'materialization_leg',
          state: 'ready',
        },
      ],
      nextSingleStep: {
        target: {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          stepKind: 'materialization_leg',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          backend: 'interpreter',
          source: 'would_dispatch',
          orchestratorId: 2,
        },
        disabledReason: null,
      },
    })
    vi.mocked(postComputeDiagnosticsSingleStep).mockResolvedValue(stuck)

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run')).toBeEnabled()
    })

    await user.click(screen.getByTestId('compute-diagnostics-run'))

    await waitFor(() => {
      expect(postComputeDiagnosticsSingleStep.mock.calls.length).toBeGreaterThanOrEqual(3)
    })
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/Run stalled/)
    })
    expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
  })

  it('Run does not wait forever on orphaned in-flight with no running dag node', async () => {
    const user = userEvent.setup()
    const afterStep = snapshotFixture({
      poolQueue: [],
      readyQueue: [],
      inFlight: [
        {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          stepKind: 'materialize',
          stepIndex: 0,
        },
      ],
      dagNodes: [
        {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          state: 'complete',
          stepKind: 'materialize',
          stepIndex: 0,
        },
      ],
      nextSingleStep: {
        target: null,
        disabledReason: 'nothing_steppable',
      },
    })
    vi.mocked(postComputeDiagnosticsSingleStep).mockResolvedValueOnce(afterStep)
    vi.mocked(fetchComputeDiagnosticsSnapshot)
      .mockResolvedValueOnce(snapshotFixture())
      .mockResolvedValueOnce(afterStep)

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run')).toBeEnabled()
    })

    await user.click(screen.getByTestId('compute-diagnostics-run'))

    await waitFor(() => {
      expect(postComputeDiagnosticsSingleStep).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
    })
    // Initial load + final settle refresh; no poll loop for the ghost in-flight row.
    expect(fetchComputeDiagnosticsSnapshot).toHaveBeenCalledTimes(2)
  })

  it('Apply allowlist refreshes until focus work appears after stream settle', async () => {
    const user = userEvent.setup()
    const afterPut = idleSnapshot({ allowlistedPlayerIds: [3] })
    const afterSettle = snapshotFixture({ allowlistedPlayerIds: [3] })
    vi.mocked(putComputeDiagnosticsAllowlist).mockResolvedValueOnce(afterPut)
    vi.mocked(fetchComputeDiagnosticsSnapshot)
      .mockResolvedValueOnce(idleSnapshot())
      .mockResolvedValueOnce(afterPut)
      .mockResolvedValueOnce(afterSettle)

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Apply allowlist')).toBeEnabled()
    })

    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.type(input, '3')
    await user.click(screen.getByText('Apply allowlist'))

    await waitFor(() => {
      expect(putComputeDiagnosticsAllowlist).toHaveBeenCalledWith(SCOPE, [3])
    })
    await waitFor(() => {
      expect(screen.getByTestId('next-single-step-preview').textContent).toContain(
        NEXT_SCOPE_KEY
      )
    })
    expect(fetchComputeDiagnosticsSnapshot.mock.calls.length).toBeGreaterThanOrEqual(3)
  })
})
describe('snapshotHasPendingPoolWork', () => {
  it('treats work_in_progress disabled reason as pending', () => {
    const snapshot = snapshotFixture({
      poolQueue: [],
      inFlight: [],
      dagNodes: [
        {
          scopeKey: 'scores@g42@p1@t8@pl2',
          analyticId: 'scores',
          state: 'running',
          stepKind: 'tier_solve',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          profileStepIndex: 1,
        },
      ],
      nextSingleStep: {
        target: null,
        disabledReason: 'work_in_progress',
      },
    })
    expect(snapshotHasPendingPoolWork(snapshot)).toBe(true)
  })

  it('treats orphaned in-flight (no running dag node) as not pending', () => {
    const snapshot = snapshotFixture({
      poolQueue: [],
      inFlight: [
        {
          scopeKey: 'fleet@g42@p1@t7@pl1',
          analyticId: 'fleet',
          stepKind: 'materialization_leg',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          backend: 'interpreter',
          orchestratorId: 1,
          startedAt: '2026-07-12T13:46:45.796588+00:00',
        },
      ],
      dagNodes: [
        {
          scopeKey: 'fleet@g42@p1@t7@pl1',
          analyticId: 'fleet',
          state: 'complete',
          stepKind: 'materialization_leg',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          profileStepIndex: 0,
        },
      ],
      nextSingleStep: {
        target: {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          stepKind: 'materialize',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          backend: 'interpreter',
          source: 'would_dispatch',
        },
        disabledReason: null,
      },
    })
    expect(snapshotHasPendingPoolWork(snapshot)).toBe(false)
  })

  it('treats in-flight with a matching running dag node as pending', () => {
    const snapshot = snapshotFixture({
      poolQueue: [],
      inFlight: [
        {
          scopeKey: 'fleet@g42@p1@t7@pl1',
          analyticId: 'fleet',
          stepKind: 'materialization_leg',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          backend: 'interpreter',
          orchestratorId: 1,
          startedAt: '2026-07-12T13:46:45.796588+00:00',
        },
      ],
      dagNodes: [
        {
          scopeKey: 'fleet@g42@p1@t7@pl1',
          analyticId: 'fleet',
          state: 'running',
          stepKind: 'materialization_leg',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          profileStepIndex: 0,
        },
      ],
    })
    expect(snapshotHasPendingPoolWork(snapshot)).toBe(true)
  })

  it('treats held next-step with empty pool queue as not steppable', () => {
    const snapshot = snapshotFixture({
      poolQueue: [],
      nextSingleStep: {
        target: {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          stepKind: 'materialization_leg',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          backend: 'interpreter',
          source: 'held',
        },
        disabledReason: null,
      },
    })
    expect(snapshotHasNextStep(snapshot)).toBe(false)
  })

  it('treats held next-step as steppable when the pool queue still has the item', () => {
    const snapshot = snapshotFixture({
      poolQueue: [
        {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          stepKind: 'materialization_leg',
          stepIndex: 0,
          state: 'held',
        },
      ],
      nextSingleStep: {
        target: {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'fleet',
          stepKind: 'materialization_leg',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          backend: 'interpreter',
          source: 'held',
        },
        disabledReason: null,
      },
    })
    expect(snapshotHasNextStep(snapshot)).toBe(true)
  })
})
