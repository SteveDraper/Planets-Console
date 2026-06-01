import { useMemo } from 'react'
import type { AnalyticShellScope } from '../api/bff'
import {
  buildStellarCartographyMapContext,
  type StellarCartographyMapContext,
  type StellarCartographyMapUiConfig,
} from '../analytics/stellar-cartography/mapUiConfig'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import { useStellarCartographyLayersStore } from '../stores/stellarCartographyLayers'
import { useShellStore } from '../stores/shell'

function useStellarCartographyMapUiConfig(): StellarCartographyMapUiConfig {
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

/**
 * Live Stellar Cartography map context from layer store, game gates, and visibility policy.
 * Mount only while Stellar Cartography is enabled on the map (see MapMainArea).
 */
export function useStellarCartographyMapContext(
  analyticScope: AnalyticShellScope
): StellarCartographyMapContext {
  const config = useStellarCartographyMapUiConfig()
  return useMemo(
    () => buildStellarCartographyMapContext(config, analyticScope),
    [config, analyticScope]
  )
}
