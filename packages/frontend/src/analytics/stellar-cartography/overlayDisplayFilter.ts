import type { StellarCartographyOverlayCircle } from '../../api/bff'
import type { StellarCartographyMapUiConfig } from '../mapLayers'
import { isCartographyLayerShown } from './layers'

/** Overlay circles visible for the current cartography UI config (render-time filter). */
export function filterCartographyOverlayCircles(
  circles: readonly StellarCartographyOverlayCircle[],
  config: StellarCartographyMapUiConfig
): StellarCartographyOverlayCircle[] {
  return circles.filter((circle) =>
    isCartographyLayerShown(circle.layer, {
      layerVisibility: config.layerVisibility,
      settingsGates: config.settingsGates,
      wormholeDisplayMode: config.wormholeDisplayMode,
      starClusterDisplayMode: config.starClusterDisplayMode,
      neutronClusterDisplayMode: config.neutronClusterDisplayMode,
    })
  )
}

/** Whether wormhole edges, nodes, and endpoint markers should render. */
export function areCartographyWormholesShown(config: StellarCartographyMapUiConfig): boolean {
  return isCartographyLayerShown('wormholes', {
    layerVisibility: config.layerVisibility,
    settingsGates: config.settingsGates,
    wormholeDisplayMode: config.wormholeDisplayMode,
    starClusterDisplayMode: config.starClusterDisplayMode,
    neutronClusterDisplayMode: config.neutronClusterDisplayMode,
  })
}
