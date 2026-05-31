import { useMemo } from 'react'
import {
  DEFAULT_STELLAR_CARTOGRAPHY_MAP_UI_CONFIG,
  type StellarCartographyMapUiConfig,
} from '../analytics/mapLayers'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import { useStellarCartographyLayersStore } from '../stores/stellarCartographyLayers'
import { useShellStore } from '../stores/shell'

export type UseStellarCartographyMapConfigOptions = {
  /** When false, returns {@link DEFAULT_STELLAR_CARTOGRAPHY_MAP_UI_CONFIG} without live store values. */
  enabled?: boolean
}

/** Canonical read site for Stellar Cartography map overlay and hover UI config. */
export function useStellarCartographyMapConfig(
  options: UseStellarCartographyMapConfigOptions = {}
): StellarCartographyMapUiConfig {
  const enabled = options.enabled ?? true
  const layerVisibility = useStellarCartographyLayersStore((s) => s.layers)
  const wormholeDisplayMode = useStellarCartographyLayersStore((s) => s.wormholeDisplayMode)
  const starClusterDisplayMode = useStellarCartographyLayersStore((s) => s.starClusterDisplayMode)
  const neutronClusterDisplayMode = useStellarCartographyLayersStore(
    (s) => s.neutronClusterDisplayMode
  )
  const settingsGates =
    useShellStore((s) => s.gameInfoContext?.stellarCartographyGates) ??
    EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES

  return useMemo(() => {
    if (!enabled) {
      return DEFAULT_STELLAR_CARTOGRAPHY_MAP_UI_CONFIG
    }
    return {
      layerVisibility,
      settingsGates,
      wormholeDisplayMode,
      starClusterDisplayMode,
      neutronClusterDisplayMode,
    }
  }, [
    enabled,
    layerVisibility,
    settingsGates,
    wormholeDisplayMode,
    starClusterDisplayMode,
    neutronClusterDisplayMode,
  ])
}
