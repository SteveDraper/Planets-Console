import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import { tileClassName } from '../tileChrome'
import {
  CARTOGRAPHY_LAYER_DEFINITIONS,
  isCartographyLayerGateEnabled,
  type CartographyLayerId,
  type StellarCartographySettingsGates,
} from './layers'
import {
  WORMHOLE_DISPLAY_MODE_LABELS,
  WORMHOLE_DISPLAY_MODES,
  type WormholeDisplayMode,
} from './wormholeDisplayMode'
import { useStellarCartographyLayersStore } from '../../stores/stellarCartographyLayers'

const ION_STORMS_EMPTY_HINT = 'No ion storms on this turn'

type StellarCartographyMapTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  settingsGates: StellarCartographySettingsGates
  /** When null, turn ion storm count is not known yet. */
  ionStormCount: number | null
}

function WormholeDisplayModeControl({
  value,
  onChange,
}: {
  value: WormholeDisplayMode
  onChange: (mode: WormholeDisplayMode) => void
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span>Wormholes</span>
      <div
        role="radiogroup"
        aria-label="Wormhole display mode"
        className="flex min-w-0 rounded border border-[#52575d] bg-slate-800/80 p-0.5"
      >
        {WORMHOLE_DISPLAY_MODES.map((mode) => {
          const selected = value === mode
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(mode)}
              className={cn(
                'min-w-0 flex-1 rounded px-1.5 py-0.5 text-[11px] leading-tight transition-colors',
                selected
                  ? 'bg-slate-600 text-slate-100'
                  : 'text-slate-400 hover:bg-black/20 hover:text-slate-200'
              )}
            >
              {WORMHOLE_DISPLAY_MODE_LABELS[mode]}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function StellarCartographyMapTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  settingsGates,
  ionStormCount,
}: StellarCartographyMapTileProps) {
  const [expanded, setExpanded] = useState(false)
  const canExpand = supportsMode && enabled
  const layers = useStellarCartographyLayersStore((s) => s.layers)
  const setLayerEnabled = useStellarCartographyLayersStore((s) => s.setLayerEnabled)
  const wormholeDisplayMode = useStellarCartographyLayersStore((s) => s.wormholeDisplayMode)
  const setWormholeDisplayMode = useStellarCartographyLayersStore((s) => s.setWormholeDisplayMode)

  useEffect(() => {
    if (!canExpand) {
      setExpanded(false)
    }
  }, [canExpand])

  const visibleLayerDefinitions = CARTOGRAPHY_LAYER_DEFINITIONS.filter((layer) =>
    isCartographyLayerGateEnabled(settingsGates, layer.id)
  )
  const showExpandedBody = canExpand && expanded
  const chevronPointsDown = showExpandedBody

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
            chevronPointsDown
              ? 'Collapse Stellar Cartography layers'
              : 'Expand Stellar Cartography layers'
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
          className="flex min-w-0 flex-col gap-1 border-t border-[#52575d]/70 px-2 pb-2 pt-1.5 text-xs text-slate-300"
          onClick={(e) => e.stopPropagation()}
        >
          {visibleLayerDefinitions.map((layer) => {
            if (layer.id === 'wormholes') {
              return (
                <WormholeDisplayModeControl
                  key={layer.id}
                  value={wormholeDisplayMode}
                  onChange={setWormholeDisplayMode}
                />
              )
            }
            const layerDisabled =
              layer.id === 'ion-storms' &&
              settingsGates.ionStorms &&
              ionStormCount === 0
            return (
              <label
                key={layer.id}
                className={cn(
                  'flex cursor-pointer items-center gap-2',
                  layerDisabled && 'cursor-not-allowed opacity-50'
                )}
                title={layerDisabled ? ION_STORMS_EMPTY_HINT : undefined}
              >
                <input
                  type="checkbox"
                  checked={layers[layer.id as Exclude<CartographyLayerId, 'wormholes'>] ?? true}
                  onChange={(e) =>
                    setLayerEnabled(
                      layer.id as Exclude<CartographyLayerId, 'wormholes'>,
                      e.target.checked
                    )
                  }
                  disabled={layerDisabled}
                  className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 accent-slate-400 disabled:opacity-50"
                />
                <span>{layer.label}</span>
              </label>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
