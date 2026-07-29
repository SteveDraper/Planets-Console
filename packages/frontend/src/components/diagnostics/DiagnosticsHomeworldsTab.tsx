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

function hasAnyHomeworldDiagnostics(snapshot: LayoutPriorReportsResponse): boolean {
  return (
    snapshot.reports.length > 0 ||
    snapshot.evidenceRefineReports.length > 0 ||
    snapshot.baselineReports.length > 0 ||
    snapshot.ensureFailures.length > 0
  )
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
        Select a game, turn, and perspective to load homeworld diagnostics.
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
    return <p className="text-sm text-slate-400">Loading homeworld diagnostics…</p>
  }

  if (snapshot == null || !hasAnyHomeworldDiagnostics(snapshot)) {
    return (
      <p className="text-sm text-slate-400">
        No homeworld diagnostics for this shell yet. Enable{' '}
        <span className="font-medium text-slate-300">Homeworld locator</span> and load the map
        or table. Evidence-refine timings appear as the ensure DAG advances; layout-prior
        reports appear after the shell solver runs (cache hits skip the solver report).
      </p>
    )
  }

  const refineSummary = snapshot.evidenceRefineSummary

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
              Layout-prior {snapshot.reports.length} · Evidence-refine{' '}
              {snapshot.evidenceRefineReports.length} · Baseline {snapshot.baselineReports.length}
              {' · '}
              Ensure failures {snapshot.ensureFailures.length}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onCopy(JSON.stringify(snapshot, null, 2))}
            className={cn(
              'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
              'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
            )}
            title="Copy homeworld diagnostics"
            aria-label="Copy homeworld diagnostics"
          >
            <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </div>

      {snapshot.ensureFailures.length > 0 ? (
        <section className="rounded border border-red-900/60 bg-[#40454a] p-3">
          <h3 className="mb-2 text-xs font-medium text-red-200">Ensure failures</h3>
          {snapshot.ensureFailures.map((report, index) => {
            const key = `ensure-fail-${String(report.capturedAt ?? index)}-${index}`
            return (
              <div key={key} className="mb-2 last:mb-0">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <p className="text-xs text-red-300/90">
                    {String(report.message ?? report.reason ?? 'ensure failure')}
                  </p>
                  <button
                    type="button"
                    onClick={() => onCopy(JSON.stringify(report, null, 2))}
                    className={cn(
                      'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
                      'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
                    )}
                    aria-label={`Copy ensure failure ${index + 1}`}
                  >
                    <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
                <DiagnosticsJsonBlock value={report} emptyLabel="Empty ensure failure" />
              </div>
            )
          })}
        </section>
      ) : null}

      {Object.keys(refineSummary).length > 0 ? (
        <section className="rounded border border-[#52575d] bg-[#40454a] p-3">
          <div className="mb-2 flex items-start justify-between gap-2">
            <h3 className="text-xs font-medium text-slate-200">Evidence-refine summary</h3>
            <button
              type="button"
              onClick={() => onCopy(JSON.stringify(refineSummary, null, 2))}
              className={cn(
                'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
                'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
              )}
              title="Copy evidence-refine summary"
              aria-label="Copy evidence-refine summary"
            >
              <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
          <DiagnosticsJsonBlock value={refineSummary} emptyLabel="Empty summary" />
        </section>
      ) : null}

      {snapshot.baselineReports.length > 0 ? (
        <section className="rounded border border-[#52575d] bg-[#40454a] p-3">
          <h3 className="mb-2 text-xs font-medium text-slate-200">Baseline reports</h3>
          {snapshot.baselineReports.map((report, index) => {
            const key = `baseline-${String(report.capturedAt ?? index)}-${index}`
            return (
              <div key={key} className="mb-2 last:mb-0">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <p className="text-xs text-slate-400">
                    recomputed={String(report.recomputed)} · candidates=
                    {String(report.candidateCount)} · inferMs={String(report.inferMs)}
                  </p>
                  <button
                    type="button"
                    onClick={() => onCopy(JSON.stringify(report, null, 2))}
                    className={cn(
                      'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
                      'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
                    )}
                    aria-label={`Copy baseline report ${index + 1}`}
                  >
                    <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
                <DiagnosticsJsonBlock value={report} emptyLabel="Empty baseline report" />
              </div>
            )
          })}
        </section>
      ) : null}

      {snapshot.evidenceRefineReports.length > 0 ? (
        <section className="rounded border border-[#52575d] bg-[#40454a] p-3">
          <h3 className="mb-2 text-xs font-medium text-slate-200">
            Evidence-refine reports (newest first, all turns)
          </h3>
          {snapshot.evidenceRefineReports.map((report, index) => {
            const key = `refine-${String(report.turn)}-${String(report.capturedAt ?? index)}`
            const outer = report.timingOuter as Record<string, unknown> | undefined
            const inner = report.timingInner as Record<string, unknown> | undefined
            return (
              <div key={key} className="mb-2 last:mb-0">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <p className="text-xs text-slate-400">
                    turn {String(report.turn)} · outer=
                    {String(outer?.totalMs ?? '?')}ms · od=
                    {String(inner?.originDistanceMs ?? '?')}ms · obsUpsert=
                    {String(inner?.observationUpsertMs ?? '?')}ms · sb=
                    {String(inner?.singleStarbaseMs ?? '?')}ms
                  </p>
                  <button
                    type="button"
                    onClick={() => onCopy(JSON.stringify(report, null, 2))}
                    className={cn(
                      'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
                      'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
                    )}
                    aria-label={`Copy evidence-refine report turn ${String(report.turn)}`}
                  >
                    <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
                <DiagnosticsJsonBlock value={report} emptyLabel="Empty refine report" />
              </div>
            )
          })}
        </section>
      ) : null}

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
              <h3 className="text-xs font-medium text-slate-200">Layout prior · {heading}</h3>
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
