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
    <aside className="flex w-56 shrink-0 flex-col gap-1 border-r border-gray-200 bg-gray-50 p-2 dark:border-gray-700 dark:bg-gray-800">
      <h2 className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
        Analytics
      </h2>
      <ul className="flex flex-col gap-0.5">
        {list.map((a) => {
          const enabled = enabledIds.has(a.id)
          const supportsMode = supportsCurrentMode(a, viewMode)
          return (
            <li key={a.id}>
              <label
                className={cn(
                  'flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm',
                  supportsMode
                    ? 'text-gray-800 dark:text-gray-200'
                    : 'cursor-default opacity-50 text-gray-500 dark:text-gray-400'
                )}
              >
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={() => supportsMode && onToggle(a.id)}
                  disabled={!supportsMode}
                  className="h-4 w-4 rounded border-gray-300 dark:border-gray-600"
                />
                <span>{a.name}</span>
              </label>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
