import type { AnalyticShellScope } from '../../api/bff'
import {
  defaultCartographyLayerVisibility,
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
  type CartographyLayerVisibility,
  type StellarCartographySettingsGates,
} from './layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
  type ClusterOutlineDisplayMode,
} from './clusterOutlineDisplayMode'
import {
  defaultWormholeDisplayMode,
  type WormholeDisplayMode,
} from './wormholeDisplayMode'

/** Cartography layer visibility and display modes for map rendering. */
export type StellarCartographyMapUiConfig = {
  layerVisibility: CartographyLayerVisibility
  settingsGates: StellarCartographySettingsGates
  wormholeDisplayMode: WormholeDisplayMode
  starClusterDisplayMode: ClusterOutlineDisplayMode
  neutronClusterDisplayMode: ClusterOutlineDisplayMode
}

/** Live cartography UI config and sample scope, passed together when the analytic is enabled. */
export type StellarCartographyMapContext = {
  config: StellarCartographyMapUiConfig
  analyticScope: AnalyticShellScope
}

export function defaultStellarCartographyMapUiConfig(): StellarCartographyMapUiConfig {
  return {
    layerVisibility: defaultCartographyLayerVisibility(),
    settingsGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
    wormholeDisplayMode: defaultWormholeDisplayMode(),
    starClusterDisplayMode: defaultStarClusterDisplayMode(),
    neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
  }
}
