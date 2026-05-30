import type { AnalyticShellScope } from '../../api/bff'
import type {
  CartographyLayerVisibility,
  StellarCartographySettingsGates,
} from '../../analytics/stellar-cartography/layers'
import type { WormholeDisplayMode } from '../../analytics/stellar-cartography/wormholeDisplayMode'
import type { ClusterOutlineDisplayMode } from '../../analytics/stellar-cartography/clusterOutlineDisplayMode'

/** Stellar Cartography map chrome passed from the shell into MapGraph. */
export type StellarCartographyMapUi = {
  layerVisibility: CartographyLayerVisibility
  settingsGates: StellarCartographySettingsGates
  wormholeDisplayMode: WormholeDisplayMode
  starClusterDisplayMode: ClusterOutlineDisplayMode
  neutronClusterDisplayMode: ClusterOutlineDisplayMode
  sampleEnabled: boolean
  analyticScope: AnalyticShellScope | null
}
