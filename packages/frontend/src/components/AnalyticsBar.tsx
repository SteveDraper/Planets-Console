import { renderShellAnalyticSidebar } from '../analytics/renderShellAnalyticSidebar'
import type { AnalyticItem, AnalyticShellScope } from '../api/bff'

type ViewMode = 'tabular' | 'map'

type AnalyticsBarProps = {
  analytics: AnalyticItem[]
  enabledIds: Set<string>
  onToggle: (id: string) => void
  viewMode: ViewMode
  turnDataReady: boolean
  analyticScope: AnalyticShellScope | null
}

/** Only analytics the user can toggle; base map is excluded from the pane. */
function selectableAnalytics(analytics: AnalyticItem[]): AnalyticItem[] {
  return analytics.filter((a) => a.type !== 'base')
}

export function AnalyticsBar({
  analytics,
  enabledIds,
  onToggle,
  viewMode,
  turnDataReady,
  analyticScope,
}: AnalyticsBarProps) {
  const list = selectableAnalytics(analytics)
  return (
    <aside className="flex w-56 min-w-0 shrink-0 flex-col gap-0.5 border-r border-[#52575d] bg-[#40454a] p-2 text-slate-200">
      <h2 className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Analytics
      </h2>
      <ul className="flex flex-col gap-1.5">
        {list.map((a) => {
          const enabled = enabledIds.has(a.id)
          return (
            <li key={a.id} className="min-w-0">
              {renderShellAnalyticSidebar({
                viewMode,
                catalogItem: a,
                enabled,
                onToggle: () => onToggle(a.id),
                turnDataReady,
                analyticScope,
              })}
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
