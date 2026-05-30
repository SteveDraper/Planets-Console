import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import { tileClassName } from '../tileChrome'
import type {
  ConnectionsFlareDepth,
  ConnectionsFlareMode,
  ConnectionsMapParams,
} from './api'

const WARP_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const

const FLARE_MODE_OPTIONS: { value: ConnectionsFlareMode; label: string }[] = [
  { value: 'off', label: 'Do not show flares' },
  { value: 'include', label: 'Show flares' },
  { value: 'only', label: 'Show only flares' },
]

const FLARE_DEPTH_OPTIONS: ConnectionsFlareDepth[] = [1, 2, 3]

type ConnectionsMapTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  connectionsMapParams: ConnectionsMapParams
  onConnectionsMapParamsChange: (next: ConnectionsMapParams) => void
}

export function ConnectionsMapTile({
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
      {showExpandedBody ? (
        <div
          className="flex min-w-0 flex-col gap-1.5 border-t border-[#52575d]/70 px-2 pb-2 pt-1.5 text-xs text-slate-300"
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
                  ? 'Max hops on mixed normal+flare paths (each hop is a normal move or a flare; the path must include at least one flare). Higher values add annulus candidates and can show longer paths; 2+ also enables illustrative waypoints in the request.'
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
