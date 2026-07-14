import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import {
  fetchComputeDiagnosticsSnapshot,
  postComputeDiagnosticsSingleStep,
  putComputeDiagnosticsAllowlist,
  putComputeDiagnosticsFreeze,
  type ComputeDiagnosticsSnapshotResponse,
  type NextSingleStepPreview,
} from '../../api/bffComputeDiagnostics'
import { analyticScopeKey } from '../../lib/analyticScopeKey'
import { cn } from '../../lib/utils'
import {
  type ClientStreamLifecycle,
  useComputeDiagnosticsStore,
} from '../../stores/computeDiagnostics'
import { DiagnosticsJsonBlock } from './DiagnosticsJsonBlock'

type ComputeDiagnosticsUiSnapshot = ComputeDiagnosticsSnapshotResponse & {
  clientStreams: ClientStreamLifecycle[]
}

type DiagnosticsComputeTabProps = {
  scope: AnalyticShellScope | null
  onCopy: (text: string) => void
}

const DISABLED_REASON_LABELS: Record<string, string> = {
  freeze_not_armed: 'Freeze is not armed',
  empty_allowlist: 'Set a focus allowlist before single-stepping',
  nothing_steppable: 'Nothing in the focus set is ready to step',
  work_in_progress: 'Focus work is still running (including persist)',
}

/** Cap runaway Run loops (deep gap-fill chains under freeze). */
const RUN_MAX_STEPS = 10_000

/** Stop Run when single-step returns the same focus target with no pool progress. */
const RUN_STALL_LIMIT = 3

const RUN_POLL_MS = 50

/** After Apply allowlist, poll briefly for stream-scheduled focus work. */
const ALLOWLIST_SETTLE_MS = 50
const ALLOWLIST_SETTLE_ATTEMPTS = 8

function nextStepFingerprint(snapshot: ComputeDiagnosticsSnapshotResponse): string | null {
  const target = snapshot.nextSingleStep.target
  if (target == null) {
    return null
  }
  return [
    String(target.scopeKey ?? ''),
    String(target.stepKind ?? ''),
    String(target.stepIndex ?? ''),
    String(target.source ?? ''),
    String(target.orchestratorId ?? ''),
  ].join('\0')
}

export function snapshotHasNextStep(snapshot: ComputeDiagnosticsSnapshotResponse): boolean {
  const target = snapshot.nextSingleStep.target
  if (target == null) {
    return false
  }
  // Held preview must still be present in the pool queue; otherwise the snapshot
  // raced (item already dequeued) and arming another held grant would stall Run.
  if (target.source === 'held') {
    const scopeKey = String(target.scopeKey ?? '')
    const stepKind = String(target.stepKind ?? '')
    const stepIndex = Number(target.stepIndex ?? 0)
    return snapshot.poolQueue.some((item) => {
      if (String(item.scopeKey ?? '') !== scopeKey) {
        return false
      }
      if (String(item.stepKind ?? '') !== stepKind) {
        return false
      }
      return Number(item.stepIndex ?? 0) === stepIndex
    })
  }
  return true
}

function runningDagStepKeys(
  snapshot: ComputeDiagnosticsSnapshotResponse
): Set<string> {
  return new Set(
    snapshot.dagNodes
      .filter((node) => node.state === 'running')
      .map(
        (node) =>
          `${String(node.scopeKey ?? '')}\0${String(node.stepKind ?? '')}\0${String(node.stepIndex ?? '')}`
      )
  )
}

/**
 * True when the pool still has queued work, focus work is marked in progress, or a
 * live in-flight execution still appears as ``running`` on a bound DAG node.
 * Orphaned in-flight rows (no matching running node) do not block Run -- those are
 * cleared by the backend finish hook, but the client must not spin if a ghost remains.
 */
export function snapshotHasPendingPoolWork(
  snapshot: ComputeDiagnosticsSnapshotResponse
): boolean {
  if (snapshot.poolQueue.length > 0) {
    return true
  }
  if (snapshot.nextSingleStep.disabledReason === 'work_in_progress') {
    return true
  }
  if (snapshot.dagNodes.some((node) => node.state === 'running')) {
    return true
  }
  if (snapshot.inFlight.length === 0) {
    return false
  }
  const running = runningDagStepKeys(snapshot)
  return snapshot.inFlight.some((item) =>
    running.has(
      `${String(item.scopeKey ?? '')}\0${String(item.stepKind ?? '')}\0${String(item.stepIndex ?? '')}`
    )
  )
}

function yieldForDiagnosticsPaint(): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, 0)
  })
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function SectionPanel({
  title,
  value,
  onCopy,
}: {
  title: string
  value: unknown
  onCopy: (text: string) => void
}) {
  return (
    <section className="rounded border border-[#52575d] bg-[#40454a] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium text-slate-200">{title}</h3>
        <button
          type="button"
          onClick={() => onCopy(JSON.stringify(value, null, 2))}
          className={cn(
            'rounded px-2 py-1 text-[10px] text-slate-300',
            'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
          )}
        >
          Copy
        </button>
      </div>
      <DiagnosticsJsonBlock value={value} />
    </section>
  )
}

const BOTTLENECK_CLASS_GUIDE = [
  {
    id: 'A',
    title: 'Serial ready-set',
    detail:
      'At most ~1 node is ready/running because dependencies or submission keep the chain serial.',
  },
  {
    id: 'B',
    title: 'Dispatch starvation',
    detail:
      'Ready set could be deep, but workers are not fed (orchestrator/inline/gates), including cross-shell pool contention.',
  },
  {
    id: 'C',
    title: 'Backend / GIL ceiling',
    detail:
      'Multiple workers in flight, but thread/interpreter choice keeps host CPU near one core except solver spikes.',
  },
  {
    id: 'D',
    title: 'Scope under-submission',
    detail:
      'Gap work for only one player (or one analytic) enters the DAG; cross-player parallelism never appears.',
  },
] as const

function BottleneckClassificationGuide() {
  const [open, setOpen] = useState(false)
  return (
    <details
      className="rounded border border-[#52575d] bg-[#40454a] p-3"
      open={open}
      onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}
      data-testid="compute-bottleneck-guide"
    >
      <summary className="cursor-pointer text-xs font-medium text-slate-200">
        Bottleneck classes A–D (manual classification)
      </summary>
      <ul className="mt-2 space-y-2 text-[11px] text-slate-300">
        {BOTTLENECK_CLASS_GUIDE.map((entry) => (
          <li key={entry.id}>
            <span className="font-medium text-slate-100">
              {entry.id}. {entry.title}
            </span>
            <span className="text-slate-400"> -- {entry.detail}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] text-slate-500">
        Use the summary strip, timeline, and rollup to classify. The rollup does not auto-label a
        class.
      </p>
    </details>
  )
}

function formatBackendMix(mix: Record<string, number> | undefined): string {
  if (mix == null) {
    return '—'
  }
  const entries = Object.entries(mix)
  if (entries.length === 0) {
    return 'none'
  }
  return entries.map(([backend, count]) => `${backend}:${count}`).join(' ')
}

function ConcurrencySummaryStrip({
  snapshot,
}: {
  snapshot: ComputeDiagnosticsSnapshotResponse
}) {
  const occupancy = snapshot.liveOccupancy
  const rollup = snapshot.concurrencyRollup
  return (
    <section
      className="rounded border border-[#52575d] bg-[#40454a] p-3"
      data-testid="compute-concurrency-summary"
    >
      <h3 className="mb-2 text-xs font-medium text-slate-200">Concurrency summary</h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-slate-300 sm:grid-cols-3">
        <div>
          <dt className="text-slate-500">Workers</dt>
          <dd className="font-mono text-slate-100">{occupancy.configuredWorkers}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Scoped ready / in-flight</dt>
          <dd className="font-mono text-slate-100">
            {occupancy.scopedReadyDepth} / {occupancy.scopedInFlightCount}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Global in-flight / queue</dt>
          <dd className="font-mono text-slate-100">
            {occupancy.globalInFlightCount} / {occupancy.globalQueueDepth}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Live backend mix</dt>
          <dd className="font-mono text-slate-100">{formatBackendMix(occupancy.backendMix)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Timeline events</dt>
          <dd className="font-mono text-slate-100">{rollup.eventCount}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Unique players (timeline)</dt>
          <dd className="font-mono text-slate-100">
            {rollup.uniquePlayers.length === 0 ? '—' : rollup.uniquePlayers.join(', ')}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Max ready / scoped IF / global IF</dt>
          <dd className="font-mono text-slate-100">
            {rollup.maxScopedReadyDepth} / {rollup.maxScopedInFlight} / {rollup.maxGlobalInFlight}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-slate-500">Backend histogram (timeline)</dt>
          <dd className="font-mono text-slate-100">
            {formatBackendMix(rollup.backendHistogram)}
          </dd>
        </div>
      </dl>
    </section>
  )
}

function nextStepSummary(preview: NextSingleStepPreview | undefined): string {
  const target = preview?.target
  if (target == null) {
    const reason = preview?.disabledReason
    if (reason != null && reason in DISABLED_REASON_LABELS) {
      return DISABLED_REASON_LABELS[reason] ?? reason
    }
    return 'No next step'
  }
  const sourceLabel = target.source === 'held' ? 'held pool item' : 'would dispatch'
  return `${target.scopeKey} · ${target.analyticId} · ${target.stepKind ?? '?'}#${target.stepIndex} · ${sourceLabel}`
}

export function DiagnosticsComputeTab({ scope, onCopy }: DiagnosticsComputeTabProps) {
  const clientStreams = useComputeDiagnosticsStore((state) => state.clientStreams)
  const freezeStatus = useComputeDiagnosticsStore((state) => state.freezeStatus)
  const setSnapshot = useComputeDiagnosticsStore((state) => state.setSnapshot)
  const setFreezeStatus = useComputeDiagnosticsStore((state) => state.setFreezeStatus)
  const [snapshot, setLocalSnapshot] = useState<ComputeDiagnosticsUiSnapshot | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [running, setRunning] = useState(false)
  const [allowlistInput, setAllowlistInput] = useState('')
  const runCancelRef = useRef(false)

  const freezeArmed =
    snapshot?.freezeArmed === true ||
    (snapshot == null && freezeStatus?.freezeArmed === true)
  const controlsBusy = pending || running

  const applySnapshot = useCallback(
    (next: ComputeDiagnosticsSnapshotResponse) => {
      const merged: ComputeDiagnosticsUiSnapshot = {
        ...next,
        clientStreams: useComputeDiagnosticsStore.getState().clientStreams,
      }
      setLocalSnapshot(merged)
      setSnapshot(merged)
      setFreezeStatus({
        shell: next.shell,
        freezeArmed: next.freezeArmed,
        allowlistedPlayerIds: next.allowlistedPlayerIds,
      })
      setAllowlistInput(next.allowlistedPlayerIds.join(','))
    },
    [setFreezeStatus, setSnapshot]
  )

  const refresh = useCallback(async () => {
    if (scope == null) {
      setLoadError('Select a game, turn, and perspective first.')
      return
    }
    setPending(true)
    setLoadError(null)
    try {
      const next = await fetchComputeDiagnosticsSnapshot(scope)
      applySnapshot(next)
    } catch (error: unknown) {
      setLoadError(error instanceof Error ? error.message : String(error))
    } finally {
      setPending(false)
    }
  }, [applySnapshot, scope])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Rehydrate allowlist input from freeze-status when the heavy snapshot is not loaded yet
  // (e.g. SPA refresh before Compute tab fetch completes).
  useEffect(() => {
    if (scope == null || freezeStatus == null || snapshot != null) {
      return
    }
    if (analyticScopeKey(freezeStatus.shell) !== analyticScopeKey(scope)) {
      return
    }
    setAllowlistInput(freezeStatus.allowlistedPlayerIds.join(','))
  }, [freezeStatus, scope, snapshot])

  useEffect(() => {
    setLocalSnapshot((current) =>
      current == null ? current : { ...current, clientStreams }
    )
    const existing = useComputeDiagnosticsStore.getState().snapshot
    if (existing != null) {
      setSnapshot({ ...existing, clientStreams })
    }
  }, [clientStreams, setSnapshot])

  const runMutation = useCallback(
    async (action: () => Promise<ComputeDiagnosticsSnapshotResponse>) => {
      if (scope == null) {
        return
      }
      setPending(true)
      setLoadError(null)
      try {
        const next = await action()
        applySnapshot(next)
      } catch (error: unknown) {
        setLoadError(error instanceof Error ? error.message : String(error))
      } finally {
        setPending(false)
      }
    },
    [applySnapshot, scope]
  )

  const applyAllowlist = useCallback(
    async (playerIds: number[]) => {
      if (scope == null) {
        return
      }
      setPending(true)
      setLoadError(null)
      try {
        let current = await putComputeDiagnosticsAllowlist(scope, playerIds)
        applySnapshot(current)
        // Allowlist narrows table streams; reconnect/scheduling often lands after the
        // PUT snapshot. Refresh until focus work appears or settle attempts expire.
        for (let attempt = 0; attempt < ALLOWLIST_SETTLE_ATTEMPTS; attempt++) {
          if (snapshotHasNextStep(current) || snapshotHasPendingPoolWork(current)) {
            break
          }
          await sleep(ALLOWLIST_SETTLE_MS)
          current = await fetchComputeDiagnosticsSnapshot(scope)
          applySnapshot(current)
        }
      } catch (error: unknown) {
        setLoadError(error instanceof Error ? error.message : String(error))
      } finally {
        setPending(false)
      }
    },
    [applySnapshot, scope]
  )

  const stopRun = useCallback(() => {
    runCancelRef.current = true
  }, [])

  const runUntilFocusIdle = useCallback(async () => {
    if (scope == null) {
      return
    }
    runCancelRef.current = false
    setRunning(true)
    setLoadError(null)
    try {
      let current: ComputeDiagnosticsSnapshotResponse =
        snapshot ??
        (await fetchComputeDiagnosticsSnapshot(scope).then((next) => {
          applySnapshot(next)
          return next
        }))
      let steps = 0
      let stallCount = 0
      while (!runCancelRef.current) {
        if (snapshotHasNextStep(current)) {
          if (steps >= RUN_MAX_STEPS) {
            setLoadError(`Run stopped after ${RUN_MAX_STEPS} steps (safety limit).`)
            break
          }
          const beforeFingerprint = nextStepFingerprint(current)
          current = await postComputeDiagnosticsSingleStep(scope)
          applySnapshot(current)
          steps += 1
          const afterFingerprint = nextStepFingerprint(current)
          const sameTarget =
            beforeFingerprint != null &&
            afterFingerprint != null &&
            beforeFingerprint === afterFingerprint
          if (sameTarget && !snapshotHasPendingPoolWork(current)) {
            stallCount += 1
            if (stallCount >= RUN_STALL_LIMIT) {
              setLoadError(
                `Run stalled: single-step did not advance ${beforeFingerprint.split('\0')[0] || 'focus target'}.`
              )
              break
            }
          } else {
            stallCount = 0
          }
          await yieldForDiagnosticsPaint()
          continue
        }
        if (snapshotHasPendingPoolWork(current)) {
          stallCount = 0
          await sleep(RUN_POLL_MS)
          if (runCancelRef.current) {
            break
          }
          current = await fetchComputeDiagnosticsSnapshot(scope)
          applySnapshot(current)
          await yieldForDiagnosticsPaint()
          continue
        }
        break
      }
      // Final refresh after focus goes idle so preview/Run match post-completion DAG state
      // (new ready work can appear after the last poll that saw an empty focus set).
      if (!runCancelRef.current) {
        current = await fetchComputeDiagnosticsSnapshot(scope)
        applySnapshot(current)
      }
    } catch (error: unknown) {
      setLoadError(error instanceof Error ? error.message : String(error))
    } finally {
      setRunning(false)
      runCancelRef.current = false
    }
  }, [applySnapshot, scope, snapshot])

  const nextStep = snapshot?.nextSingleStep
  const singleStepDisabledReason = useMemo(() => {
    if (!freezeArmed) {
      return DISABLED_REASON_LABELS.freeze_not_armed
    }
    if (nextStep?.disabledReason != null) {
      return DISABLED_REASON_LABELS[nextStep.disabledReason] ?? nextStep.disabledReason
    }
    if (nextStep?.target == null) {
      return DISABLED_REASON_LABELS.nothing_steppable
    }
    return null
  }, [freezeArmed, nextStep])

  const runDisabledReason = useMemo(() => {
    if (running) {
      return null
    }
    if (!freezeArmed) {
      return DISABLED_REASON_LABELS.freeze_not_armed
    }
    if (nextStep?.disabledReason === 'empty_allowlist') {
      return DISABLED_REASON_LABELS.empty_allowlist
    }
    if (
      nextStep?.target == null &&
      nextStep?.disabledReason === 'nothing_steppable' &&
      snapshot != null &&
      !snapshotHasPendingPoolWork(snapshot)
    ) {
      return DISABLED_REASON_LABELS.nothing_steppable
    }
    return null
  }, [freezeArmed, nextStep, running, snapshot])

  if (scope == null) {
    return (
      <p className="text-sm text-slate-400">
        Select a game, turn, and perspective to inspect compute orchestration.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {loadError != null ? (
        <p className="text-sm text-red-400" role="alert">
          {loadError}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={controlsBusy}
          onClick={() => void refresh()}
          className={cn(
            'rounded border border-[#52575d] px-2 py-1 text-xs text-slate-200',
            'hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50'
          )}
        >
          Refresh
        </button>
        <button
          type="button"
          disabled={controlsBusy || freezeArmed}
          onClick={() => void runMutation(() => putComputeDiagnosticsFreeze(scope, true))}
          className={cn(
            'rounded border border-amber-700/60 px-2 py-1 text-xs text-amber-200',
            'hover:bg-amber-900/20 disabled:cursor-not-allowed disabled:opacity-50'
          )}
        >
          Arm freeze
        </button>
        <button
          type="button"
          disabled={controlsBusy || !freezeArmed}
          onClick={() => void runMutation(() => putComputeDiagnosticsFreeze(scope, false))}
          className={cn(
            'rounded border border-[#52575d] px-2 py-1 text-xs text-slate-200',
            'hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50'
          )}
        >
          Disarm freeze
        </button>
        <button
          type="button"
          disabled={controlsBusy || singleStepDisabledReason != null}
          title={singleStepDisabledReason ?? undefined}
          onClick={() => void runMutation(() => postComputeDiagnosticsSingleStep(scope))}
          className={cn(
            'rounded border border-[#52575d] px-2 py-1 text-xs text-slate-200',
            'hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50'
          )}
        >
          Single step
        </button>
        <button
          type="button"
          disabled={!running && runDisabledReason != null}
          title={
            running
              ? 'Stop automated single-stepping'
              : (runDisabledReason ?? 'Single-step until the focus set has no remaining work')
          }
          onClick={() => {
            if (running) {
              stopRun()
              return
            }
            void runUntilFocusIdle()
          }}
          className={cn(
            'rounded border px-2 py-1 text-xs',
            running
              ? 'border-amber-700/60 text-amber-200 hover:bg-amber-900/20'
              : 'border-[#52575d] text-slate-200 hover:bg-white/10',
            'disabled:cursor-not-allowed disabled:opacity-50'
          )}
          data-testid="compute-diagnostics-run"
        >
          {running ? 'Stop' : 'Run'}
        </button>
      </div>

      <label className="flex flex-col gap-1 text-xs text-slate-300">
        <span>
          Focus player IDs (comma-separated) -- allowlist selects who to observe and
          single-step; it does not free-run those players
        </span>
        <div className="flex gap-2">
          <input
            type="text"
            value={allowlistInput}
            onChange={(event) => setAllowlistInput(event.target.value)}
            disabled={controlsBusy || !freezeArmed}
            className="min-w-0 flex-1 rounded border border-[#52575d] bg-[#2d3136] px-2 py-1 text-slate-100"
          />
          <button
            type="button"
            disabled={controlsBusy || !freezeArmed}
            onClick={() => {
              const playerIds = allowlistInput
                .split(',')
                .map((part) => part.trim())
                .filter((part) => part.length > 0)
                .map((part) => Number.parseInt(part, 10))
                .filter((value) => Number.isFinite(value))
              void applyAllowlist(playerIds)
            }}
            className={cn(
              'rounded border border-[#52575d] px-2 py-1 text-xs text-slate-200',
              'hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50'
            )}
          >
            Apply allowlist
          </button>
        </div>
      </label>

      {freezeArmed ? (
        <p className="text-xs text-slate-400" data-testid="next-single-step-preview">
          Next single-step: {nextStepSummary(nextStep)}
          {running ? ' · Running…' : null}
          {!running && singleStepDisabledReason != null
            ? ` (${singleStepDisabledReason})`
            : null}
        </p>
      ) : null}

      {snapshot == null ? (
        <p className="text-sm text-slate-400">
          {controlsBusy ? 'Loading…' : 'No snapshot yet.'}
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <BottleneckClassificationGuide />
          <ConcurrencySummaryStrip snapshot={snapshot} />
          <SectionPanel
            title="Freeze state"
            value={{
              freezeArmed: snapshot.freezeArmed,
              allowlistedPlayerIds: snapshot.allowlistedPlayerIds,
              shell: snapshot.shell,
              nextSingleStep: snapshot.nextSingleStep,
            }}
            onCopy={onCopy}
          />
          <SectionPanel title="Live occupancy" value={snapshot.liveOccupancy} onCopy={onCopy} />
          <SectionPanel
            title="Concurrency timeline"
            value={snapshot.concurrencyTimeline}
            onCopy={onCopy}
          />
          <SectionPanel
            title="Concurrency rollup"
            value={snapshot.concurrencyRollup}
            onCopy={onCopy}
          />
          <SectionPanel title="Pool queue" value={snapshot.poolQueue} onCopy={onCopy} />
          <SectionPanel title="In-flight" value={snapshot.inFlight} onCopy={onCopy} />
          <SectionPanel title="Remote pool" value={snapshot.remotePool} onCopy={onCopy} />
          <SectionPanel title="DAG nodes" value={snapshot.dagNodes} onCopy={onCopy} />
          <SectionPanel title="Ready queue" value={snapshot.readyQueue} onCopy={onCopy} />
          <SectionPanel title="Completion history" value={snapshot.completionHistory} onCopy={onCopy} />
          <SectionPanel title="Server streams" value={snapshot.serverStreams} onCopy={onCopy} />
          <SectionPanel title="Client streams" value={snapshot.clientStreams} onCopy={onCopy} />
        </div>
      )}
    </div>
  )
}
