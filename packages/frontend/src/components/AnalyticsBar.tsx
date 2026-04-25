import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../lib/utils'
import type {
  AnalyticItem,
  ConnectionsFlareDepth,
  ConnectionsFlareMode,
  ConnectionsMapParams,
} from '../api/bff'

type ViewMode = 'tabular' | 'map'

type AnalyticsBarProps = {
  analytics: AnalyticItem[]
  enabledIds: Set<string>
  onToggle: (id: string) => void
  viewMode: ViewMode
  connectionsMapParams: ConnectionsMapParams
  onConnectionsMapParamsChange: (next: ConnectionsMapParams) => void
}

function supportsCurrentMode(a: AnalyticItem, viewMode: ViewMode): boolean {
  return viewMode === 'tabular' ? a.supportsTable : a.supportsMap
}

/** Only analytics the user can toggle; base map is excluded from the pane. */
function selectableAnalytics(analytics: AnalyticItem[]): AnalyticItem[] {
  return analytics.filter((a) => a.type !== 'base')
}

const WARP_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const

const FLARE_MODE_OPTIONS: { value: ConnectionsFlareMode; label: string }[] = [
  { value: 'off', label: 'Do not show flares' },
  { value: 'include', label: 'Show flares' },
  { value: 'only', label: 'Show only flares' },
]

const FLARE_DEPTH_OPTIONS: ConnectionsFlareDepth[] = [1, 2, 3]

type TileChrome = {
  supportsMode: boolean
  depressed: boolean
}

function tileClassName({ supportsMode, depressed }: TileChrome): string {
  return cn(
    'rounded border text-sm transition-shadow',
    supportsMode ? 'text-slate-200' : 'cursor-default opacity-50 text-slate-500',
    depressed
      ? 'border-t-[#2a2d30] border-l-[#2a2d30] border-b-[#5a5f65] border-r-[#5a5f65] bg-[#383c41] shadow-[inset_1px_1px_2px_0_rgba(0,0,0,0.3)]'
      : 'border-t-[#5a5f65] border-l-[#5a5f65] border-b-[#2a2d30] border-r-[#2a2d30] bg-[#464b51] shadow-[inset_1px_1px_0_0_rgba(255,255,255,0.06)]'
  )
}

type ConnectionsMapTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  connectionsMapParams: ConnectionsMapParams
  onConnectionsMapParamsChange: (next: ConnectionsMapParams) => void
}

function ConnectionsMapTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  connectionsMapParams,
  onConnectionsMapParamsChange,
}: ConnectionsMapTileProps) {
  const [expanded, setExpanded] = useState(false)
  const canExpand = supportsMode && enabled

  useEffect(() => {
    if (!canExpand) {
      setExpanded(false)
    }
  }, [canExpand])

  const showExpandedBody = canExpand && expanded
  const chevronPointsDown = showExpandedBody
  const flaresEnabled = connectionsMapParams.flareMode !== 'off'

  return (
    <div
      className={cn(
        tileClassName({ supportsMode, depressed }),
        'flex min-w-0 max-w-full flex-col'
      )}
    >
      <div className="flex items-center gap-1 py-1.5 pl-2 pr-0.5">
        <label
          className={cn(
            'flex min-w-0 flex-1 cursor-pointer items-center gap-2 py-0.5',
            !supportsMode && 'cursor-default'
          )}
        >
          <input
            type="checkbox"
            checked={enabled}
            onChange={() => supportsMode && onToggle()}
            disabled={!supportsMode}
            className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
          />
          <span className="min-w-0 truncate">{name}</span>
        </label>
        <button
          type="button"
          aria-expanded={chevronPointsDown}
          aria-label={
            chevronPointsDown ? 'Collapse Connections options' : 'Expand Connections options'
          }
          disabled={!canExpand}
          onClick={() => canExpand && setExpanded((v) => !v)}
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 transition-colors',
            canExpand &&
              'hover:bg-black/15 hover:text-slate-200 focus-visible:outline focus-visible:ring-1 focus-visible:ring-slate-500',
            !canExpand && 'cursor-default opacity-40'
          )}
        >
          <ChevronDown
            className={cn(
              'h-4 w-4 shrink-0 transition-transform duration-150',
              !chevronPointsDown && '-rotate-90'
            )}
            aria-hidden
          />
        </button>
      </div>
      {enabled && supportsMode ? (
        <div
          className="flex min-w-0 flex-col gap-1 border-b border-[#52575d]/40 px-2 pb-2 text-xs text-slate-300"
          onClick={(e) => e.stopPropagation()}
        >
          <label className="flex min-w-0 w-full items-center gap-1.5">
            <span className="w-11 shrink-0 text-slate-400">Flares</span>
            <select
              value={connectionsMapParams.flareMode}
              onChange={(e) =>
                onConnectionsMapParamsChange({
                  ...connectionsMapParams,
                  flareMode: e.target.value as ConnectionsFlareMode,
                })
              }
              className="min-w-0 w-0 flex-1 rounded border border-[#52575d] bg-[#2a2d30] px-1 py-0.5 text-slate-200"
            >
              {FLARE_MODE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-0 w-full items-center gap-1.5">
            <span className="w-11 shrink-0 text-slate-400">Depth</span>
            <select
              value={connectionsMapParams.flareDepth}
              onChange={(e) =>
                onConnectionsMapParamsChange({
                  ...connectionsMapParams,
                  flareDepth: Number(e.target.value) as ConnectionsFlareDepth,
                })
              }
              disabled={!flaresEnabled}
              title={
                flaresEnabled
                  ? 'Cap on how many flares in a row to search. At 2 or 3 you still get every link that was shown at 1, plus new links that need a longer chain.'
                  : 'Enable flares to set depth'
              }
              className="min-w-0 w-0 flex-1 rounded border border-[#52575d] bg-[#2a2d30] px-1 py-0.5 text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {FLARE_DEPTH_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}
      {showExpandedBody ? (
        <div
          className="flex min-w-0 flex-col gap-1.5 border-t border-[#52575d]/70 px-2 pb-2 pt-1.5 text-xs text-slate-300"
          onClick={(e) => e.stopPropagation()}
        >
          <label className="flex min-w-0 w-full items-center gap-1.5">
            <span className="w-11 shrink-0 text-slate-400">Warp</span>
            <select
              value={connectionsMapParams.warpSpeed}
              onChange={(e) =>
                onConnectionsMapParamsChange({
                  ...connectionsMapParams,
                  warpSpeed: Number(e.target.value),
                })
              }
              disabled={!supportsMode}
              className="min-w-0 w-0 flex-1 rounded border border-[#52575d] bg-[#2a2d30] px-1 py-0.5 text-slate-200 disabled:opacity-50"
            >
              {WARP_OPTIONS.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
          </label>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={connectionsMapParams.gravitonicMovement}
              onChange={(e) =>
                onConnectionsMapParamsChange({
                  ...connectionsMapParams,
                  gravitonicMovement: e.target.checked,
                })
              }
              disabled={!supportsMode}
              className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 accent-slate-400 disabled:opacity-50"
            />
            <span>Gravitonic movement</span>
          </label>
        </div>
      ) : null}
    </div>
  )
}

export function AnalyticsBar({
  analytics,
  enabledIds,
  onToggle,
  viewMode,
  connectionsMapParams,
  onConnectionsMapParamsChange,
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
