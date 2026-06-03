import { ClipboardCopy } from 'lucide-react'
import {
  fetchDiagnosticsRecent,
  type DiagnosticsRecentItem,
} from '../../api/bff'
import { cn } from '../../lib/utils'
import { DiagnosticsJsonBlock } from './DiagnosticsJsonBlock'

type DiagnosticsRequestsTabProps = {
  items: DiagnosticsRecentItem[] | null
  loadError: string | null
  onCopy: (text: string) => void
}

function diagnosticsByNewestFirst(list: DiagnosticsRecentItem[]): DiagnosticsRecentItem[] {
  return [...list].sort((a, b) => b.capturedAt.localeCompare(a.capturedAt))
}

function formatBlob(item: DiagnosticsRecentItem): string {
  return JSON.stringify(
    { capturedAt: item.capturedAt, summary: item.summary, diagnostics: item.diagnostics },
    null,
    2
  )
}

export function DiagnosticsRequestsTab({
  items,
  loadError,
  onCopy,
}: DiagnosticsRequestsTabProps) {
  if (loadError != null) {
    return (
      <p className="text-sm text-red-400" role="alert">
        {loadError}
      </p>
    )
  }
  if (items == null) {
    return <p className="text-sm text-slate-400">Loading…</p>
  }
  if (items.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No entries yet. Turn on{' '}
        <span className="font-medium text-slate-300">Record BFF diagnostics</span> above, then
        trigger a BFF request in the console.
      </p>
    )
  }

  return (
    <ul className="flex flex-col gap-3">
      {diagnosticsByNewestFirst(items).map((item) => {
        const label = item.summary || item.capturedAt
        return (
          <li
            key={`${item.capturedAt}-${item.summary}`}
            className="rounded border border-[#52575d] bg-[#40454a] p-2"
          >
            <div className="mb-1 flex items-center justify-between gap-2">
              <span
                className="min-w-0 flex-1 truncate text-xs text-slate-200"
                title={label}
              >
                {label}
              </span>
              <button
                type="button"
                onClick={() => onCopy(formatBlob(item))}
                className={cn(
                  'inline-flex shrink-0 items-center gap-1 rounded p-1 text-slate-300',
                  'hover:bg-white/10 focus:outline-none focus:ring-1 focus:ring-slate-400'
                )}
                title="Copy this entry"
                aria-label="Copy to clipboard"
              >
                <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
            <DiagnosticsJsonBlock value={item} maxHeightClassName="max-h-40" />
          </li>
        )
      })}
    </ul>
  )
}

export async function loadDiagnosticsRecentItems(): Promise<DiagnosticsRecentItem[]> {
  const response = await fetchDiagnosticsRecent()
  return response.items
}

export function formatAllDiagnosticsItems(items: DiagnosticsRecentItem[]): string {
  return JSON.stringify(
    {
      items: diagnosticsByNewestFirst(items).map((item) => ({
        capturedAt: item.capturedAt,
        summary: item.summary,
        diagnostics: item.diagnostics,
      })),
    },
    null,
    2
  )
}
