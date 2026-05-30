import { cn } from '../lib/utils'
import { ConnectionsMapTile } from '../analytics/connections/ConnectionsMapTile'
import { StellarCartographyMapTile } from '../analytics/stellar-cartography/StellarCartographyMapTile'
import { tileClassName } from '../analytics/tileChrome'
import type { StellarCartographySettingsGates } from '../analytics/stellar-cartography/layers'
import type { AnalyticItem, ConnectionsMapParams } from '../api/bff'

type ViewMode = 'tabular' | 'map'

type AnalyticsBarProps = {
  analytics: AnalyticItem[]
  enabledIds: Set<string>
  onToggle: (id: string) => void
  viewMode: ViewMode
  connectionsMapParams: ConnectionsMapParams
  onConnectionsMapParamsChange: (next: ConnectionsMapParams) => void
  stellarCartographyGates: StellarCartographySettingsGates
  cartographySettingsKnown: boolean
  ionStormCount: number | null
}

function supportsCurrentMode(a: AnalyticItem, viewMode: ViewMode): boolean {
  return viewMode === 'tabular' ? a.supportsTable : a.supportsMap
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
  connectionsMapParams,
  onConnectionsMapParamsChange,
  stellarCartographyGates,
  cartographySettingsKnown,
  ionStormCount,
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
          const supportsMode = supportsCurrentMode(a, viewMode)
          const depressed = enabled && supportsMode
          const isConnectionsMap = a.id === 'connections' && viewMode === 'map'
          const isStellarCartographyMap = a.id === 'stellar-cartography' && viewMode === 'map'

          if (isConnectionsMap) {
            return (
              <li key={a.id} className="min-w-0">
                <ConnectionsMapTile
                  name={a.name}
                  enabled={enabled}
                  supportsMode={supportsMode}
                  depressed={depressed}
                  onToggle={() => onToggle(a.id)}
                  connectionsMapParams={connectionsMapParams}
                  onConnectionsMapParamsChange={onConnectionsMapParamsChange}
                />
              </li>
            )
          }

          if (isStellarCartographyMap) {
            return (
              <li key={a.id} className="min-w-0">
                <StellarCartographyMapTile
                  name={a.name}
                  enabled={enabled}
                  supportsMode={supportsMode}
                  depressed={depressed}
                  onToggle={() => onToggle(a.id)}
                  settingsGates={stellarCartographyGates}
                  cartographySettingsKnown={cartographySettingsKnown}
                  ionStormCount={ionStormCount}
                />
              </li>
            )
          }

          return (
            <li key={a.id}>
              <label
                className={cn(
                  'flex cursor-pointer items-center gap-2 px-2 py-1.5',
                  tileClassName({ supportsMode, depressed })
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
