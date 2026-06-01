import type { AnalyticShellScope } from '../../api/bff'
import {
  cartographyVisibilityPolicy,
  type CartographyVisibilityPolicy,
} from './cartographyVisibilityPolicy'
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

/** Live cartography UI config, visibility policy, and sample scope when the analytic is enabled. */
export type StellarCartographyMapContext = {
  config: StellarCartographyMapUiConfig
  policy: CartographyVisibilityPolicy
  analyticScope: AnalyticShellScope
}

export function buildStellarCartographyMapContext(
  config: StellarCartographyMapUiConfig,
  analyticScope: AnalyticShellScope
): StellarCartographyMapContext {
  return {
    config,
    policy: cartographyVisibilityPolicy(config),
    analyticScope,
  }
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
