import { cn } from '../lib/utils'
import type { AnalyticItem } from '../api/bff'

type ViewMode = 'tabular' | 'map'

type AnalyticsBarProps = {
  analytics: AnalyticItem[]
  enabledIds: Set<string>
  onToggle: (id: string) => void
  viewMode: ViewMode
}

function supportsCurrentMode(a: AnalyticItem, viewMode: ViewMode): boolean {
  return viewMode === 'tabular' ? a.supportsTable : a.supportsMap
}

/** Only analytics the user can toggle; base map is excluded from the pane. */
function selectableAnalytics(analytics: AnalyticItem[]): AnalyticItem[] {
  return analytics.filter((a) => a.type !== 'base')
}

export function AnalyticsBar({ analytics, enabledIds, onToggle, viewMode }: AnalyticsBarProps) {
  const list = selectableAnalytics(analytics)
  return (
    <aside className="flex w-56 shrink-0 flex-col gap-0.5 border-r border-[#52575d] bg-[#40454a] p-2 text-slate-200">
      <h2 className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Analytics
      </h2>
      <ul className="flex flex-col gap-1.5">
        {list.map((a) => {
          const enabled = enabledIds.has(a.id)
          const supportsMode = supportsCurrentMode(a, viewMode)
          const depressed = enabled && supportsMode
          return (
            <li key={a.id}>
              <label
                className={cn(
                  'flex cursor-pointer items-center gap-2 rounded border px-2 py-1.5 text-sm transition-shadow',
                  supportsMode ? 'text-slate-200' : 'cursor-default opacity-50 text-slate-500',
                  depressed
                    ? 'border-t-[#2a2d30] border-l-[#2a2d30] border-b-[#5a5f65] border-r-[#5a5f65] bg-[#383c41] shadow-[inset_1px_1px_2px_0_rgba(0,0,0,0.3)]'
                    : 'border-t-[#5a5f65] border-l-[#5a5f65] border-b-[#2a2d30] border-r-[#2a2d30] bg-[#464b51] shadow-[inset_1px_1px_0_0_rgba(255,255,255,0.06)]'
                )}
              >
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={() => supportsMode && onToggle(a.id)}
                  disabled={!supportsMode}
                  className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
                />
                <span className="min-w-0 truncate">{a.name}</span>
              </label>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
