import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  ComputeDiagnosticsSingleStepResponse,
  ComputeDiagnosticsSnapshotResponse,
} from '../../api/bffComputeDiagnostics'
import { useComputeDiagnosticsStore } from '../../stores/computeDiagnostics'
import {
  DiagnosticsComputeTab,
} from './DiagnosticsComputeTab'

const jsonBlockRenders = vi.hoisted(() => ({ count: 0 }))

vi.mock('./DiagnosticsJsonBlock', () => ({
  DiagnosticsJsonBlock: ({ value }: { value: unknown }) => {
    jsonBlockRenders.count += 1
    return <pre>{Array.isArray(value) ? `Array(${value.length})` : 'value'}</pre>
  },
}))

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

function emptyRemotePool(): ComputeDiagnosticsSnapshotResponse['remotePool'] {
  const emptyBackend = {
    maxWorkers: null,
    queueDepth: null,
    counts: { pending: 0, running: 0, done: 0, cancelled: 0 },
    futures: [] as Record<string, unknown>[],
  }
  return { interpreter: emptyBackend, process: { ...emptyBackend, futures: [] } }
}

function emptyLiveOccupancy(): ComputeDiagnosticsSnapshotResponse['liveOccupancy'] {
  return {
    configuredWorkers: 4,
    scopedReadyDepth: 0,
    scopedInFlightCount: 0,
    globalInFlightCount: 0,
    globalQueueDepth: 0,
    backendMix: {},
  }
}

function emptyConcurrencyRollup(): ComputeDiagnosticsSnapshotResponse['concurrencyRollup'] {
  return {
    eventCount: 0,
    uniquePlayers: [],
    backendHistogram: {},
    durationByBackendMs: {},
    scopedReadyDepth: { p50: null, p95: null, max: null },
    scopedInFlight: { p50: null, p95: null, max: null },
    globalInFlight: { p50: null, p95: null, max: null },
    maxScopedReadyDepth: 0,
    maxScopedInFlight: 0,
    maxGlobalInFlight: 0,
    configuredWorkers: null,
  }
}

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
    recentFailures: [],
    serverStreams: [],
    remotePool: emptyRemotePool(),
    liveOccupancy: emptyLiveOccupancy(),
    concurrencyTimeline: [],
    concurrencyRollup: emptyConcurrencyRollup(),
    ...overrides,
  }
}

function stepped(
  snapshot: ComputeDiagnosticsSnapshotResponse,
  released = true
): ComputeDiagnosticsSingleStepResponse {
  return { ...snapshot, released }
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

  it('does not treat a stale freeze status for another shell as armed', async () => {
    useComputeDiagnosticsStore.setState({
      freezeStatus: {
        shell: { ...SCOPE, gameId: '999001' },
        freezeArmed: true,
        allowlistedPlayerIds: [],
      },
    })
    vi.mocked(fetchComputeDiagnosticsSnapshot).mockImplementation(() => new Promise(() => {}))

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    expect(screen.getAllByTitle('Freeze is not armed').length).toBeGreaterThan(0)
  })

  it('a client stream event re-renders only the client streams panel', async () => {
    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('DAG nodes')).toBeInTheDocument()
    })
    const rendersBefore = jsonBlockRenders.count

    act(() => {
      useComputeDiagnosticsStore.getState().upsertClientStream({
        streamId: 'fleet',
        connectionKey: 'fleet:628580:8:1:1',
        generation: 1,
        lastEventAt: new Date().toISOString(),
        lastEventType: 'ledger_updated',
        lastConnectResult: null,
      })
    })

    expect(jsonBlockRenders.count - rendersBefore).toBe(1)
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

  it('shows A-D guide, concurrency summary strip, and copyable timeline/rollup', async () => {
    const user = userEvent.setup()
    const onCopy = vi.fn()
    vi.mocked(fetchComputeDiagnosticsSnapshot).mockResolvedValue(
      snapshotFixture({
        liveOccupancy: {
          configuredWorkers: 4,
          scopedReadyDepth: 2,
          scopedInFlightCount: 1,
          globalInFlightCount: 3,
          globalQueueDepth: 5,
          backendMix: { thread: 1 },
        },
        concurrencyTimeline: [{ kind: 'ready', scopeKey: NEXT_SCOPE_KEY }],
        concurrencyRollup: {
          ...emptyConcurrencyRollup(),
          eventCount: 1,
          uniquePlayers: [1],
          backendHistogram: { thread: 1 },
          maxScopedReadyDepth: 2,
          maxScopedInFlight: 1,
          maxGlobalInFlight: 3,
          configuredWorkers: 4,
        },
      })
    )
    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={onCopy} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-concurrency-summary')).toBeTruthy()
    })
    const summary = screen.getByTestId('compute-concurrency-summary')
    expect(summary.textContent).toContain('4')
    expect(summary.textContent).toContain('2 / 1')
    expect(summary.textContent).toContain('thread:1')

    expect(screen.getByTestId('compute-bottleneck-guide').textContent).toContain(
      'Bottleneck classes A–D'
    )
    expect(screen.getByText('Concurrency timeline')).toBeTruthy()
    expect(screen.getByText('Concurrency rollup')).toBeTruthy()

    const timelineHeading = screen.getByText('Concurrency timeline')
    const timelineSection = timelineHeading.closest('section')
    expect(timelineSection).not.toBeNull()
    await user.click(within(timelineSection as HTMLElement).getByRole('button', { name: 'Copy' }))
    expect(JSON.parse(onCopy.mock.calls[0]?.[0] as string)).toEqual([
      { kind: 'ready', scopeKey: NEXT_SCOPE_KEY },
    ])
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
      .mockResolvedValueOnce(stepped(afterFirst))
      .mockResolvedValueOnce(stepped(idleSnapshot()))
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
      expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
    })
    expect(screen.getByTestId('next-single-step-preview').textContent).toContain(
      'Nothing in the focus set is ready to step'
    )
    // Initial load + one confirming poll after the focus set went idle.
    expect(fetchComputeDiagnosticsSnapshot).toHaveBeenCalledTimes(2)
  })

  it('Run polls while focus work is in progress, then stops after a confirming idle poll', async () => {
    const user = userEvent.setup()
    const inProgress = snapshotFixture({
      poolQueue: [],
      readyQueue: [],
      nextSingleStep: { target: null, disabledReason: 'work_in_progress' },
    })
    vi.mocked(postComputeDiagnosticsSingleStep).mockResolvedValueOnce(stepped(inProgress))
    vi.mocked(fetchComputeDiagnosticsSnapshot)
      .mockResolvedValueOnce(snapshotFixture())
      .mockResolvedValueOnce(inProgress)
      .mockResolvedValueOnce(idleSnapshot())
      .mockResolvedValueOnce(idleSnapshot())

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run')).toBeEnabled()
    })

    await user.click(screen.getByTestId('compute-diagnostics-run'))

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
    })
    expect(postComputeDiagnosticsSingleStep).toHaveBeenCalledTimes(1)
    expect(fetchComputeDiagnosticsSnapshot).toHaveBeenCalledTimes(4)
  })

  it('Run stops with an error after repeated single-steps that release nothing', async () => {
    const user = userEvent.setup()
    const refused = snapshotFixture({
      poolQueue: [],
      readyQueue: [
        {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'scores',
          stepKind: 'tier_solve',
          state: 'ready',
        },
      ],
      nextSingleStep: {
        target: {
          scopeKey: NEXT_SCOPE_KEY,
          analyticId: 'scores',
          stepKind: 'tier_solve',
          stepIndex: 0,
          priorityBand: 'stream_attached',
          backend: 'interpreter',
          source: 'would_dispatch',
          orchestratorId: 2,
        },
        disabledReason: null,
      },
    })
    vi.mocked(fetchComputeDiagnosticsSnapshot).mockResolvedValue(refused)
    vi.mocked(postComputeDiagnosticsSingleStep).mockResolvedValue(stepped(refused, false))

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run')).toBeEnabled()
    })

    await user.click(screen.getByTestId('compute-diagnostics-run'))

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/did not release/)
    })
    expect(postComputeDiagnosticsSingleStep).toHaveBeenCalledTimes(3)
    expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
  })

  it('Run waits for a worker when a released held target is still queued', async () => {
    const user = userEvent.setup()
    const heldStillQueued = snapshotFixture()
    vi.mocked(postComputeDiagnosticsSingleStep)
      .mockResolvedValueOnce(stepped(heldStillQueued))
      .mockResolvedValueOnce(stepped(idleSnapshot()))
    vi.mocked(fetchComputeDiagnosticsSnapshot)
      .mockResolvedValueOnce(snapshotFixture())
      .mockResolvedValueOnce(heldStillQueued)
      .mockResolvedValue(idleSnapshot())

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run')).toBeEnabled()
    })

    await user.click(screen.getByTestId('compute-diagnostics-run'))

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
    })
    const [firstStep, secondStep] = vi.mocked(postComputeDiagnosticsSingleStep).mock
      .invocationCallOrder
    const pollsBetween = vi
      .mocked(fetchComputeDiagnosticsSnapshot)
      .mock.invocationCallOrder.filter((order) => order > firstStep && order < secondStep)
    expect(pollsBetween).toHaveLength(1)
  })

  it('Run is enabled while freeze is armed before the first snapshot loads', async () => {
    useComputeDiagnosticsStore.setState({
      freezeStatus: { shell: SCOPE, freezeArmed: true, allowlistedPlayerIds: [1] },
    })
    vi.mocked(fetchComputeDiagnosticsSnapshot).mockRejectedValueOnce(new Error('offline'))

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/offline/)
    })
    expect(screen.getByTestId('compute-diagnostics-run')).toBeEnabled()
  })

  it('Run stops when only non-focus held work remains in the pool queue', async () => {
    const user = userEvent.setup()
    const nonFocusHeld = idleSnapshot({
      poolQueue: [{ scopeKey: 'fleet@t4,p2', analyticId: 'fleet', stepKind: 'materialize' }],
    })
    vi.mocked(postComputeDiagnosticsSingleStep).mockResolvedValueOnce(stepped(nonFocusHeld))
    vi.mocked(fetchComputeDiagnosticsSnapshot)
      .mockResolvedValueOnce(snapshotFixture())
      .mockResolvedValue(nonFocusHeld)

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run')).toBeEnabled()
    })

    await user.click(screen.getByTestId('compute-diagnostics-run'))

    await waitFor(() => {
      expect(screen.getByTestId('compute-diagnostics-run').textContent).toBe('Run')
    })
    expect(postComputeDiagnosticsSingleStep).toHaveBeenCalledTimes(1)
    expect(fetchComputeDiagnosticsSnapshot).toHaveBeenCalledTimes(2)
  })

  it('Apply allowlist shows the snapshot the PUT returns, without polling', async () => {
    const user = userEvent.setup()
    const afterPut = snapshotFixture({ allowlistedPlayerIds: [3] })
    vi.mocked(putComputeDiagnosticsAllowlist).mockResolvedValueOnce(afterPut)
    vi.mocked(fetchComputeDiagnosticsSnapshot).mockResolvedValueOnce(idleSnapshot())

    render(<DiagnosticsComputeTab scope={SCOPE} onCopy={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText('Apply allowlist')).toBeEnabled()
    })

    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.type(input, '3')
    await user.click(screen.getByText('Apply allowlist'))

    await waitFor(() => {
      expect(screen.getByTestId('next-single-step-preview').textContent).toContain(
        NEXT_SCOPE_KEY
      )
    })
    expect(putComputeDiagnosticsAllowlist).toHaveBeenCalledWith(SCOPE, [3])
    expect(fetchComputeDiagnosticsSnapshot).toHaveBeenCalledTimes(1)
  })
})
