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
import { CartographyDisplayModeControl } from './CartographyDisplayModeControl'
import {
  CLUSTER_OUTLINE_DISPLAY_MODE_LABELS,
  CLUSTER_OUTLINE_DISPLAY_MODES,
  type ClusterOutlineDisplayMode,
} from './clusterOutlineDisplayMode'
import {
  WORMHOLE_DISPLAY_MODE_LABELS,
  WORMHOLE_DISPLAY_MODES,
  type WormholeDisplayMode,
} from './wormholeDisplayMode'
import { useShellStore } from '../../stores/shell'
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
    <CartographyDisplayModeControl
      label="Wormholes"
      ariaLabel="Wormhole display mode"
      modes={WORMHOLE_DISPLAY_MODES}
      modeLabels={WORMHOLE_DISPLAY_MODE_LABELS}
      value={value}
      onChange={onChange}
    />
  )
}

function ClusterOutlineDisplayModeControl({
  label,
  value,
  onChange,
}: {
  label: string
  value: ClusterOutlineDisplayMode
  onChange: (mode: ClusterOutlineDisplayMode) => void
}) {
  return (
    <CartographyDisplayModeControl
      label={label}
      ariaLabel={`${label} display mode`}
      modes={CLUSTER_OUTLINE_DISPLAY_MODES}
      modeLabels={CLUSTER_OUTLINE_DISPLAY_MODE_LABELS}
      value={value}
      onChange={onChange}
    />
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
  const cartographySettingsKnown = useShellStore((s) => s.gameInfoContext != null)
  const [expanded, setExpanded] = useState(false)
  const canExpand = supportsMode && enabled
  const layers = useStellarCartographyLayersStore((s) => s.layers)
  const setLayerEnabled = useStellarCartographyLayersStore((s) => s.setLayerEnabled)
  const wormholeDisplayMode = useStellarCartographyLayersStore((s) => s.wormholeDisplayMode)
  const setWormholeDisplayMode = useStellarCartographyLayersStore((s) => s.setWormholeDisplayMode)
  const starClusterDisplayMode = useStellarCartographyLayersStore((s) => s.starClusterDisplayMode)
  const setStarClusterDisplayMode = useStellarCartographyLayersStore(
    (s) => s.setStarClusterDisplayMode
  )
  const neutronClusterDisplayMode = useStellarCartographyLayersStore(
    (s) => s.neutronClusterDisplayMode
  )
  const setNeutronClusterDisplayMode = useStellarCartographyLayersStore(
    (s) => s.setNeutronClusterDisplayMode
  )

  useEffect(() => {
    if (!canExpand) {
      setExpanded(false)
    }
  }, [canExpand])

  const visibleLayerDefinitions = cartographySettingsKnown
    ? CARTOGRAPHY_LAYER_DEFINITIONS.filter((layer) =>
        isCartographyLayerGateEnabled(settingsGates, layer.id)
      )
    : CARTOGRAPHY_LAYER_DEFINITIONS
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
            if (layer.id === 'star-clusters') {
              return (
                <ClusterOutlineDisplayModeControl
                  key={layer.id}
                  label={layer.label}
                  value={starClusterDisplayMode}
                  onChange={setStarClusterDisplayMode}
                />
              )
            }
            if (layer.id === 'neutron-clusters') {
              return (
                <ClusterOutlineDisplayModeControl
                  key={layer.id}
                  label={layer.label}
                  value={neutronClusterDisplayMode}
                  onChange={setNeutronClusterDisplayMode}
                />
              )
            }
            const layerDisabled =
              cartographySettingsKnown &&
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
                  checked={layers[layer.id as Exclude<
                    CartographyLayerId,
                    'wormholes' | 'star-clusters' | 'neutron-clusters'
                  >] ?? true}
                  onChange={(e) =>
                    setLayerEnabled(
                      layer.id as Exclude<
                        CartographyLayerId,
                        'wormholes' | 'star-clusters' | 'neutron-clusters'
                      >,
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
