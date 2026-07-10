import { useCallback, useEffect, useState } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import {
  fetchComputeDiagnosticsSnapshot,
  postComputeDiagnosticsSingleStep,
  putComputeDiagnosticsAllowlist,
  putComputeDiagnosticsFreeze,
  type ComputeDiagnosticsSnapshotResponse,
} from '../../api/bffComputeDiagnostics'
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

export function DiagnosticsComputeTab({ scope, onCopy }: DiagnosticsComputeTabProps) {
  const clientStreams = useComputeDiagnosticsStore((state) => state.clientStreams)
  const setSnapshot = useComputeDiagnosticsStore((state) => state.setSnapshot)
  const setFreezeStatus = useComputeDiagnosticsStore((state) => state.setFreezeStatus)
  const [snapshot, setLocalSnapshot] = useState<ComputeDiagnosticsUiSnapshot | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [allowlistInput, setAllowlistInput] = useState('')

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
          disabled={pending}
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
          disabled={pending || snapshot?.freezeArmed === true}
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
          disabled={pending || snapshot?.freezeArmed !== true}
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
          disabled={pending || snapshot?.freezeArmed !== true}
          onClick={() => void runMutation(() => postComputeDiagnosticsSingleStep(scope))}
          className={cn(
            'rounded border border-[#52575d] px-2 py-1 text-xs text-slate-200',
            'hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50'
          )}
        >
          Single step
        </button>
      </div>

      <label className="flex flex-col gap-1 text-xs text-slate-300">
        <span>Allowlisted player IDs (comma-separated)</span>
        <div className="flex gap-2">
          <input
            type="text"
            value={allowlistInput}
            onChange={(event) => setAllowlistInput(event.target.value)}
            disabled={pending || snapshot?.freezeArmed !== true}
            className="min-w-0 flex-1 rounded border border-[#52575d] bg-[#2d3136] px-2 py-1 text-slate-100"
          />
          <button
            type="button"
            disabled={pending || snapshot?.freezeArmed !== true}
            onClick={() => {
              const playerIds = allowlistInput
                .split(',')
                .map((part) => part.trim())
                .filter((part) => part.length > 0)
                .map((part) => Number.parseInt(part, 10))
                .filter((value) => Number.isFinite(value))
              void runMutation(() => putComputeDiagnosticsAllowlist(scope, playerIds))
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

      {snapshot == null ? (
        <p className="text-sm text-slate-400">{pending ? 'Loading…' : 'No snapshot yet.'}</p>
      ) : (
        <div className="flex flex-col gap-3">
          <SectionPanel
            title="Freeze state"
            value={{
              freezeArmed: snapshot.freezeArmed,
              allowlistedPlayerIds: snapshot.allowlistedPlayerIds,
              shell: snapshot.shell,
            }}
            onCopy={onCopy}
          />
          <SectionPanel title="Pool queue" value={snapshot.poolQueue} onCopy={onCopy} />
          <SectionPanel title="In-flight" value={snapshot.inFlight} onCopy={onCopy} />
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
