import { cn } from '../../lib/utils'
import { AnalyticSidebarTile, analyticDetailCheckboxClassName } from '../AnalyticSidebarTile'
import {
  CARTOGRAPHY_LAYER_DEFINITIONS,
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
  isCartographyLayerGateEnabled,
  type CartographyLayerId,
} from './layers'
import { useStellarCartographyTurnSummary } from './useStellarCartographyTurnSummary'
import type { AnalyticShellScope } from '../../api/bff'
import { DisplayModeControl } from '../DisplayModeControl'
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
  turnDataReady: boolean
  analyticScope: AnalyticShellScope | null
}

function WormholeDisplayModeControl({
  value,
  onChange,
}: {
  value: WormholeDisplayMode
  onChange: (mode: WormholeDisplayMode) => void
}) {
  return (
    <DisplayModeControl
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
    <DisplayModeControl
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
  turnDataReady,
  analyticScope,
}: StellarCartographyMapTileProps) {
  const cartographySettingsKnown = useShellStore((s) => s.gameInfoContext != null)
  const settingsGates =
    useShellStore((s) => s.gameInfoContext?.stellarCartographyGates) ??
    EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES
  const { data: stellarCartographyTurnSummary } = useStellarCartographyTurnSummary({
    analyticScope,
    turnDataReady,
    ionStormsGate: settingsGates.ionStorms,
  })
  const ionStormCount =
    settingsGates.ionStorms && turnDataReady && analyticScope != null
      ? (stellarCartographyTurnSummary?.ionStormCount ?? null)
      : null
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

  const visibleLayerDefinitions = cartographySettingsKnown
    ? CARTOGRAPHY_LAYER_DEFINITIONS.filter((layer) =>
        isCartographyLayerGateEnabled(settingsGates, layer.id)
      )
    : CARTOGRAPHY_LAYER_DEFINITIONS

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      detailsLabel="Stellar Cartography layers"
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
              className={analyticDetailCheckboxClassName}
            />
            <span>{layer.label}</span>
          </label>
        )
      })}
    </AnalyticSidebarTile>
  )
}
