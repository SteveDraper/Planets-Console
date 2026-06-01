import { useMemo } from 'react'
import type { StellarCartographyMapUiConfig } from '../analytics/stellar-cartography/mapUiConfig'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import { useStellarCartographyLayersStore } from '../stores/stellarCartographyLayers'
import { useShellStore } from '../stores/shell'

/**
 * Live Stellar Cartography map overlay and hover UI config from layer store and game gates.
 * Mount only while Stellar Cartography is enabled on the map (see MapShellContent).
 */
export function useStellarCartographyMapConfig(): StellarCartographyMapUiConfig {
  const layerVisibility = useStellarCartographyLayersStore((s) => s.layers)
  const wormholeDisplayMode = useStellarCartographyLayersStore((s) => s.wormholeDisplayMode)
  const starClusterDisplayMode = useStellarCartographyLayersStore((s) => s.starClusterDisplayMode)
  const neutronClusterDisplayMode = useStellarCartographyLayersStore(
    (s) => s.neutronClusterDisplayMode
  )
  const settingsGates =
    useShellStore((s) => s.gameInfoContext?.stellarCartographyGates) ??
    EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES

  return useMemo(
    () => ({
      layerVisibility,
      settingsGates,
      wormholeDisplayMode,
      starClusterDisplayMode,
      neutronClusterDisplayMode,
    }),
    [
      layerVisibility,
      settingsGates,
      wormholeDisplayMode,
      starClusterDisplayMode,
      neutronClusterDisplayMode,
    ]
  )
}
