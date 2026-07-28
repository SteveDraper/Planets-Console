import { ClipboardCopy } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import {
  fetchLayoutPriorReports,
  type LayoutPriorReportsResponse,
} from '../../api/bffLayoutPriorDiagnostics'
import { cn } from '../../lib/utils'
import { DiagnosticsJsonBlock } from './DiagnosticsJsonBlock'

type DiagnosticsHomeworldsTabProps = {
  scope: AnalyticShellScope | null
  onCopy: (text: string) => void
  /** When true, reload reports (modal open / tab focus). */
  isActive: boolean
  onSnapshotChange?: (snapshot: LayoutPriorReportsResponse | null) => void
}

export function DiagnosticsHomeworldsTab({
  scope,
  onCopy,
  isActive,
  onSnapshotChange,
}: DiagnosticsHomeworldsTabProps) {
  const [snapshot, setSnapshot] = useState<LayoutPriorReportsResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (!isActive) return
    if (scope == null) {
      setSnapshot(null)
      onSnapshotChange?.(null)
      setLoadError(null)
      return
    }
    let cancelled = false
    setIsLoading(true)
    setLoadError(null)
    void fetchLayoutPriorReports(scope)
      .then((body) => {
        if (cancelled) return
        setSnapshot(body)
        onSnapshotChange?.(body)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setSnapshot(null)
        onSnapshotChange?.(null)
        setLoadError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isActive, scope, onSnapshotChange])

  if (scope == null) {
    return (
      <p className="text-sm text-slate-400">
        Select a game, turn, and perspective to load homeworld layout-prior solver reports.
      </p>
    )
  }

  if (loadError != null) {
    return (
      <p className="text-sm text-red-400" role="alert">
        {loadError}
      </p>
    )
  }

  if (isLoading && snapshot == null) {
    return <p className="text-sm text-slate-400">Loading layout-prior reports…</p>
  }

  if (snapshot == null || snapshot.reports.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No layout-prior solver reports for this shell yet. Enable{' '}
        <span className="font-medium text-slate-300">Homeworld locator</span> and load the map
        or table so materialize runs the solver (cache hits do not record a report).
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded border border-[#52575d] bg-[#40454a] p-3 text-xs text-slate-300">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p>
              Game <span className="font-medium text-slate-200">{snapshot.shell.gameId}</span>
              {' · '}
              Turn <span className="font-medium text-slate-200">{snapshot.shell.turn}</span>
              {' · '}
              Perspective{' '}
              <span className="font-medium text-slate-200">{snapshot.shell.perspective}</span>
            </p>
            <p className="mt-1 text-slate-500">
              {snapshot.reports.length} report{snapshot.reports.length === 1 ? '' : 's'} (newest
              first)
            </p>
          </div>
          <button
            type="button"
            onClick={() => onCopy(JSON.stringify(snapshot, null, 2))}
            className={cn(
              'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
              'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
            )}
            title="Copy homeworld layout-prior reports"
            aria-label="Copy homeworld layout-prior reports"
          >
            <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </div>

      {snapshot.reports.map((report, index) => {
        const key = `${String(report.capturedAt ?? index)}-${String(report.solver ?? '')}-${index}`
        const heading = [
          String(report.solver ?? 'solver'),
          report.stopReason != null ? `stop=${String(report.stopReason)}` : null,
          report.capturedAt != null ? String(report.capturedAt) : null,
        ]
          .filter(Boolean)
          .join(' · ')
        return (
          <section key={key} className="rounded border border-[#52575d] bg-[#40454a] p-3">
            <div className="mb-2 flex items-start justify-between gap-2">
              <h3 className="text-xs font-medium text-slate-200">{heading}</h3>
              <button
                type="button"
                onClick={() => onCopy(JSON.stringify(report, null, 2))}
                className={cn(
                  'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
                  'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
                )}
                title="Copy report JSON"
                aria-label={`Copy layout-prior report ${index + 1}`}
              >
                <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
            <DiagnosticsJsonBlock value={report} emptyLabel="Empty report" />
          </section>
        )
      })}
    </div>
  )
}
