import { AnalyticSidebarTile } from '../AnalyticSidebarTile'
import type { ConnectionsFlareDepth, ConnectionsFlareMode } from './api'
import { useConnectionsMapParamsStore } from './connectionsMapParamsStore'

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
}

export function ConnectionsMapTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
}: ConnectionsMapTileProps) {
  const connectionsMapParams = useConnectionsMapParamsStore((s) => s.connectionsMapParams)
  const setConnectionsMapParams = useConnectionsMapParamsStore((s) => s.setConnectionsMapParams)
  const flaresEnabled = connectionsMapParams.flareMode !== 'off'

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      detailsLabel="Connections options"
    >
      <label className="flex min-w-0 w-full items-center gap-1.5">
        <span className="w-11 shrink-0 text-slate-400">Flares</span>
        <select
          value={connectionsMapParams.flareMode}
          onChange={(e) =>
            setConnectionsMapParams({
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
            setConnectionsMapParams({
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
            setConnectionsMapParams({
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
            setConnectionsMapParams({
              ...connectionsMapParams,
              gravitonicMovement: e.target.checked,
            })
          }
          disabled={!supportsMode}
          className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 accent-slate-400 disabled:opacity-50"
        />
        <span>Gravitonic movement</span>
      </label>
    </AnalyticSidebarTile>
  )
}
