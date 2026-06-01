import type { MapEdge, StellarCartographyOverlayCircle } from '../../api/bff'
import type { StellarCartographyMapUiConfig } from './mapUiConfig'
import { isCartographyLayerShown } from './layers'
import { filterWormholeEdgesForDisplayMode } from './wormholeDisplayMode'

/** Overlay circles visible for the current cartography UI config (render-time filter). */
export function filterCartographyOverlayCircles(
  circles: readonly StellarCartographyOverlayCircle[],
  config: StellarCartographyMapUiConfig
): StellarCartographyOverlayCircle[] {
  return circles.filter((circle) => isCartographyLayerShown(circle.layer, config))
}

/** Whether wormhole edges, nodes, and endpoint markers should render. */
export function areCartographyWormholesShown(config: StellarCartographyMapUiConfig): boolean {
  return isCartographyLayerShown('wormholes', config)
}

/**
 * Wormhole map edges visible for the current cartography UI config.
 * Applies settings gates and display mode (including on-hover reveal).
 */
export function filterWormholeEdgesForCartographyConfig(
  edges: readonly MapEdge[],
  config: StellarCartographyMapUiConfig,
  revealCellKey: string | null
): MapEdge[] {
  if (!areCartographyWormholesShown(config)) {
    return edges.filter((edge) => edge.layer !== 'wormholes')
  }
  return filterWormholeEdgesForDisplayMode(
    edges,
    config.wormholeDisplayMode,
    revealCellKey
  )
}
