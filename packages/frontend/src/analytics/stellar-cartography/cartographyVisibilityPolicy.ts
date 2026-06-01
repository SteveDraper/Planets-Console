import type {
  MapEdge,
  StellarCartographyOverlayCircle,
  StellarCartographySampleEntry,
} from '../../api/bff'
import { isStellarCartographySampleLayerId } from '../../api/bff'
import type { CartographyLayerId } from './layers'
import { isCartographyLayerShown } from './layers'
import type { StellarCartographyMapUiConfig } from './mapUiConfig'
import { filterWormholeEdgesForDisplayMode } from './wormholeDisplayMode'

/** Visibility and filtering rules shared by map rendering and hover sampling. */
export type CartographyVisibilityPolicy = {
  isLayerShown: (layerId: CartographyLayerId) => boolean
  overlayCircles: (
    circles: readonly StellarCartographyOverlayCircle[]
  ) => StellarCartographyOverlayCircle[]
  sampleEntries: (
    entries: readonly StellarCartographySampleEntry[]
  ) => StellarCartographySampleEntry[]
  areWormholesShown: () => boolean
  mapEdges: (edges: readonly MapEdge[], wormholeLineRevealKey: string | null) => MapEdge[]
}

export function cartographyVisibilityPolicy(
  config: StellarCartographyMapUiConfig
): CartographyVisibilityPolicy {
  const isLayerShown = (layerId: CartographyLayerId) =>
    isCartographyLayerShown(layerId, config)

  return {
    isLayerShown,
    overlayCircles: (circles) => circles.filter((circle) => isLayerShown(circle.layer)),
    sampleEntries: (entries) =>
      entries.filter(
        (entry): entry is StellarCartographySampleEntry =>
          isStellarCartographySampleLayerId(entry.layer) && isLayerShown(entry.layer)
      ),
    areWormholesShown: () => isLayerShown('wormholes'),
    mapEdges: (edges, wormholeLineRevealKey) => {
      if (!isLayerShown('wormholes')) {
        return edges.filter((edge) => edge.layer !== 'wormholes')
      }
      return filterWormholeEdgesForDisplayMode(
        edges,
        config.wormholeDisplayMode,
        wormholeLineRevealKey
      )
    },
  }
}
