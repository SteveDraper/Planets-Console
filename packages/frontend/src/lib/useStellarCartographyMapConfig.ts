import { useMemo } from 'react'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import type { StellarCartographyMapUiConfig } from '../analytics/mapLayers'
import { useStellarCartographyLayersStore } from '../stores/stellarCartographyLayers'
import { useShellStore } from '../stores/shell'

/** Canonical read site for Stellar Cartography map overlay and hover UI config. */
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
